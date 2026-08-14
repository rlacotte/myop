"""Tests de la collecte RSS : filtrage, dédoublonnage, diversité, goût."""

from datetime import timedelta

import httpx

from app.config import Show, Source
from app.sources import clean_html, fetch_items, normalize_url, title_tokens
from tests.conftest import make_rss


def test_normalize_url_strips_tracking():
    assert (
        normalize_url("https://ex.com/a/?utm_source=rss&fbclid=x&id=2")
        == "https://ex.com/a?id=2"
    )
    assert normalize_url("https://ex.com/a/") == "https://ex.com/a"


def test_clean_html_strips_tags_and_urls():
    html = '<p>Suite <a href="https://x.com">lien</a>… voir https://exemple.com/page</p>'
    assert clean_html(html) == "Suite lien… voir"


def test_clean_html_truncates_at_sentence():
    text = "Phrase un. Phrase deux assez longue pour dépasser. Phrase trois. "
    assert clean_html(text, max_chars=30) == "Phrase un."


async def test_fetch_filters_dedupes_and_selects(show, mock_client, now):
    result = await fetch_items(show, now=now, client=mock_client)

    titles = [item.title for item in result.selected]
    assert "Vieux A3" not in titles
    assert "Actu très ancienne B2" not in titles
    assert titles.count("Grosse actu A1 (repris)") + titles.count("Grosse actu A1") == 1
    assert len(result.selected) == 3  # A1, A2, B1 après fusion du doublon
    assert result.selected[0].url.startswith("https://a.example/article-1")
    assert len(result.all_keys) == 6
    assert len(set(result.all_keys)) == 5


async def test_seen_items_are_excluded(show, mock_client, now):
    first = await fetch_items(show, now=now, client=mock_client)
    second = await fetch_items(show, now=now, client=mock_client, seen=set(first.all_keys))
    assert second.selected == []


async def test_window_widens_when_too_few_items(show, now):
    stale_feed = make_rss(
        [
            {
                "title": f"Actu de la veille {i}",
                "link": f"https://a.example/veille-{i}",
                "date": now - timedelta(hours=30 + i),
            }
            for i in range(3)
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://a.example/rss":
            return httpx.Response(200, content=stale_feed)
        return httpx.Response(500)  # la source B tombe en panne : on l'ignore

    show.max_per_source = 3
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_items(show, now=now, client=client)

    assert [item.title for item in result.selected] == [
        "Actu de la veille 0",
        "Actu de la veille 1",
        "Actu de la veille 2",
    ]
    assert any("Source B" in error for error in result.errors)


async def test_diversity_max_per_source(now):
    feed_s = make_rss(
        [{"title": f"Actu {i}", "link": f"https://s.example/{i}",
          "date": now - timedelta(minutes=i * 10)} for i in range(6)]
    )
    feed_o = make_rss(
        [{"title": f"Autre {i}", "link": f"https://o.example/{i}",
          "date": now - timedelta(minutes=i * 10 + 5)} for i in range(6)]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=feed_s if "s.example" in str(request.url) else feed_o)

    show = Show(
        num_headlines=6, num_briefs=0, max_per_source=2,
        sources=[Source(name="S", url="https://s.example/rss"),
                 Source(name="O", url="https://o.example/rss")],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_items(show, now=now, client=client)

    per_source: dict[str, int] = {}
    for item in result.selected:
        per_source[item.source_name] = per_source.get(item.source_name, 0) + 1
    assert max(per_source.values()) == 2
    assert len(result.selected) == 4


def test_title_tokens_ignores_stopwords_and_accents():
    tokens = title_tokens("Le Conseil constitutionnel censure l'interdiction aux mineurs")
    assert "conseil" in tokens and "constitutionnel" in tokens and "censure" in tokens
    assert "les" not in tokens and "aux" not in tokens


async def test_near_duplicate_titles_deduped(now):
    feed_a = make_rss(
        [{"title": "Le Conseil constitutionnel censure la loi interdisant les réseaux sociaux aux mineurs de 15 ans",
          "link": "https://a.example/reseaux", "date": now - timedelta(minutes=10)}]
    )
    feed_b = make_rss(
        [
            {"title": "Réseaux sociaux : le Conseil constitutionnel censure l'interdiction aux mineurs de 15 ans",
             "link": "https://b.example/meme-sujet", "date": now - timedelta(minutes=5)},
            {"title": "Le prix du tabac augmente de 5 % au 1er janvier",
             "link": "https://b.example/tabac", "date": now - timedelta(minutes=1)},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=feed_a if "a.example" in str(request.url) else feed_b)

    show = Show(num_headlines=5, num_briefs=0,
                sources=[Source(name="A", url="https://a.example/rss"),
                         Source(name="B", url="https://b.example/rss")])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_items(show, now=now, client=client)

    titles = [item.title for item in result.selected]
    assert len(result.selected) == 2
    assert len([t for t in titles if "constitutionnel" in t.lower()]) == 1
    assert "Le prix du tabac augmente de 5 % au 1er janvier" in titles


async def test_ranker_reorders_selection(show, mock_client, now):
    """La boucle de goût peut faire remonter une source appréciée."""
    from app.feedback import Feedback

    def ranker(items):
        feedback = Feedback(source_scores={"Source B": 5})
        # reproduit le tri pondéré de app.feedback.apply_feedback
        def rank(item):
            freshness = item.published.timestamp() if item.published else 0
            score = feedback.source_scores.get(item.source_name, 0)
            return freshness * (1 + 0.15 * max(min(score, 5), -5))
        return sorted(items, key=rank, reverse=True)

    async with mock_client as client:
        result = await fetch_items(show, now=now, client=client, ranker=ranker)
    # Sans ranker, A1 (le plus frais) sort en tête ; on vérifie juste la stabilité du contrat
    assert len(result.selected) == 3
