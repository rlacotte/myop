"""Tests de la collecte RSS : filtrage, dédoublonnage, diversité des sources."""

from datetime import timedelta

import httpx

from app.config import Config, Source
from app.sources import clean_html, fetch_items, normalize_url
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


async def test_fetch_filters_dedupes_and_selects(config, mock_client, now):
    result = await fetch_items(config, now=now, client=mock_client)

    titles = [item.title for item in result.selected]
    # Vieux articles exclus, doublon cross-source « Grosse actu A1 » conservé une fois
    assert "Vieux A3" not in titles
    assert "Actu très ancienne B2" not in titles
    assert titles.count("Grosse actu A1 (repris)") + titles.count("Grosse actu A1") == 1
    # 3 items frais uniques après dédoublonnage : A1, A2, B1 (A1 repris fondu avec l'original)
    assert len(result.selected) == 3
    # Le plus récent d'abord
    assert result.selected[0].url.startswith("https://a.example/article-1")
    # Toutes les clés vues sont historisées pour seen.json (5 uniques sur 6 items)
    assert len(result.all_keys) == 6
    assert len(set(result.all_keys)) == 5


async def test_seen_items_are_excluded(config, mock_client, now):
    first = await fetch_items(config, now=now, client=mock_client)
    second = await fetch_items(
        config, now=now, client=mock_client, seen=set(first.all_keys)
    )
    assert second.selected == []


async def test_window_widens_when_too_few_items(config, now):
    """Moins de 3 items dans les 24 h → la fenêtre s'élargit à 48 h."""
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

    config.max_per_source = 3  # les 3 items viennent tous de la source A
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_items(config, now=now, client=client)

    assert [item.title for item in result.selected] == [
        "Actu de la veille 0",
        "Actu de la veille 1",
        "Actu de la veille 2",
    ]
    # La panne de la source B est signalée
    assert any("Source B" in error for error in result.errors)


async def test_diversity_max_per_source(now):
    """La sélection ne dépasse pas max_per_source pour une même source."""
    feed_s = make_rss(
        [
            {
                "title": f"Actu {i}",
                "link": f"https://s.example/{i}",
                "date": now - timedelta(minutes=i * 10),
            }
            for i in range(6)
        ]
    )
    feed_o = make_rss(
        [
            {
                "title": f"Autre {i}",
                "link": f"https://o.example/{i}",
                "date": now - timedelta(minutes=i * 10 + 5),
            }
            for i in range(6)
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=feed_s if "s.example" in str(request.url) else feed_o
        )

    config = Config(
        num_headlines=6,
        num_briefs=0,
        max_per_source=2,
        sources=[
            Source(name="S", url="https://s.example/rss"),
            Source(name="O", url="https://o.example/rss"),
        ],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_items(config, now=now, client=client)

    per_source: dict[str, int] = {}
    for item in result.selected:
        per_source[item.source_name] = per_source.get(item.source_name, 0) + 1
    assert max(per_source.values()) == 2
    assert len(result.selected) == 4
