"""Tests des modules enrichis : météo, liste de lecture, boucle de goût, pipeline v2."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from pydub import AudioSegment

from app import generate
from app.config import Config, Show, Source
from app.feedback import Feedback, apply_feedback, load_feedback, record_vote, save_feedback
from app.generate import generate_episode, load_seen, save_seen
from app.reading import ReadingItem, extract_article, load_queue, save_queue, take_for_episode
from app.sources import FeedItem, FetchResult
from app.tts import SynthResult
from app.weather import Weather, fetch_weather, weather_text

PARIS = ZoneInfo("Europe/Paris")


# ------------------------------------------------------------------- météo --

async def test_fetch_weather_success():
    def handler(request: httpx.Request) -> httpx.Response:
        if "geocoding" in str(request.url):
            return httpx.Response(200, json={"results": [{"name": "Paris", "latitude": 48.8, "longitude": 2.3}]})
        return httpx.Response(200, json={"daily": {
            "temperature_2m_min": [14.2], "temperature_2m_max": [26.7],
            "precipitation_probability_max": [10], "weather_code": [0],
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        weather = await fetch_weather("Paris", client=client)
    assert weather is not None
    assert weather.temp_min == 14 and weather.temp_max == 27
    assert "dégagé" in weather.sky
    text = weather_text(weather)
    assert "Paris" in text and "14" in text and "27" in text


async def test_fetch_weather_failure_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_weather("NullePart", client=client) is None


# ---------------------------------------------------------- liste de lecture --

def test_extract_article():
    html = """
    <html><head><title>Grand titre</title></head><body>
      <nav>menu</nav>
      <p>""" + "Un paragraphe assez long pour être retenu. " * 8 + """</p>
      <p>Autre paragraphe tout aussi long et significatif pour l'extraction. """ + "Détails. " * 20 + """</p>
    </body></html>"""
    title, text = extract_article(html, "https://ex.com/a")
    assert title == "Grand titre"
    assert "paragraphe" in text.lower()


def test_reading_queue_roundtrip_and_consume(tmp_path):
    queue = [ReadingItem(url="https://a.example/1", title="A", text="x" * 50)]
    save_queue(tmp_path, queue)
    assert len(load_queue(tmp_path)) == 1

    due = take_for_episode(tmp_path, max_items=3)
    assert [item.title for item in due] == ["A"]
    assert load_queue(tmp_path) == []  # consommé


# ------------------------------------------------------------- boucle de goût --

def test_record_vote_and_apply(tmp_path):
    feedback = record_vote(tmp_path, source="Le Monde", title="Super actu géniale", good=True)
    assert feedback.source_scores["Le Monde"] == 1

    feedback = record_vote(tmp_path, source="Next", title="Encore du football ennuyeux", good=False)
    assert feedback.source_scores["Next"] == -1
    assert any(token in feedback.disliked_keywords for token in ("football", "ennuyeux"))

    persisted = load_feedback(tmp_path)
    assert persisted.source_scores["Le Monde"] == 1


def _item(title, source, published):
    return FeedItem(title=title, url=f"https://x/{title}", published=published,
                    summary="", source_name=source, guid=f"g-{title}")


def test_apply_feedback_filters_and_boosts():
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    loved = _item("Actu récente media B", "Media B", now - timedelta(hours=1))
    fresh = _item("Actu encore plus récente media A", "Media A", now - timedelta(minutes=10))
    hated = _item("Match de football ce soir", "Media A", now - timedelta(minutes=5))
    feedback = Feedback(source_scores={"Media B": 4}, disliked_keywords=["football"])

    ranked = apply_feedback([hated, loved, fresh], feedback)
    assert all("football" not in item.title for item in ranked)  # sujet détesté écarté
    assert ranked[0].source_name == "Media B"  # la source aimée gagne des places


# ------------------------------------------------------------- pipeline v2 --

async def _fake_fetch(show, *, now=None, seen=None, client=None, ranker=None):
    items = [
        FeedItem(
            title=f"Actu {i}", url=f"https://ex.com/{i}",
            published=now - timedelta(hours=1),
            summary=f"Résumé de l'actu {i}.", source_name="Test", guid=f"g{i}",
        )
        for i in range(3)
    ]
    return FetchResult(selected=items, all_keys=[item.key for item in items])


async def _fake_synthesize(segments, show, config, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio = AudioSegment.silent(duration=len(segments) * 600, frame_rate=24000)
    audio.export(out_path, format="mp3", bitrate="48k")
    return SynthResult(
        out_path, len(audio) // 1000,
        [{"title": "Intro", "start_ms": 0, "end_ms": len(audio)}],
    )


async def _fake_weather(city, client=None):
    return Weather(city=city, temp_min=14.0, temp_max=26.0, sky="un ciel dégagé", rain_prob=10)


async def test_generate_episode_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "fetch_items", _fake_fetch)
    monkeypatch.setattr(generate, "synthesize", _fake_synthesize)
    monkeypatch.setattr(generate, "fetch_weather", _fake_weather)

    config = Config(
        shows=[Show(id="matin", title="Podcast Test", num_headlines=3, num_briefs=2,
                    sources=[Source(name="Test", url="https://ex.com/rss")],
                    weather_city="Paris")],
        ai={"enabled": False},
        github={"pages_base": "https://me.github.io/myop/"},
    )
    now = datetime(2026, 8, 14, 7, 30, tzinfo=PARIS)
    result = await generate_episode(config, config.show(), tmp_path, now=now)

    assert result.ok
    assert result.episode_id == "2026-08-14"
    assert result.show_id == "matin"
    assert result.episode_path.exists()
    assert result.chapter_titles == ["Intro"]  # chapitres simulés
    assert result.titles == ["Actu 0", "Actu 1", "Actu 2"]

    meta = json.loads((tmp_path / "episodes" / "matin" / "2026-08-14.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Briefing du vendredi 14 août"
    seen = json.loads((tmp_path / "seen-matin.json").read_text(encoding="utf-8"))
    assert set(seen) == {"https://ex.com/0", "https://ex.com/1", "https://ex.com/2"}
    assert (tmp_path / "podcast.xml").exists()
    assert (tmp_path / "cover.png").exists()
    assert (tmp_path / "index.html").exists()
    xml = (tmp_path / "podcast.xml").read_text(encoding="utf-8")
    assert "https://me.github.io/myop/episodes/matin/2026-08-14.mp3" in xml


async def test_generate_two_shows_two_feeds(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "fetch_items", _fake_fetch)
    monkeypatch.setattr(generate, "synthesize", _fake_synthesize)
    monkeypatch.setattr(generate, "fetch_weather", _fake_weather)

    config = Config(
        shows=[
            Show(id="matin", title="Le Matin", sources=[Source(name="T", url="https://ex.com/rss")]),
            Show(id="soir", title="Le Soir", sources=[Source(name="T", url="https://ex.com/rss")]),
        ],
        ai={"enabled": False},
        github={"pages_base": "https://me.github.io/myop/"},
    )
    now = datetime(2026, 8, 14, 7, 30, tzinfo=PARIS)
    for show in config.shows:
        result = await generate_episode(config, show, tmp_path, now=now)
        assert result.ok and result.show_id == show.id

    assert (tmp_path / "podcast.xml").exists()          # 1ʳᵉ émission
    assert (tmp_path / "podcast-soir.xml").exists()     # 2ᵉ émission
    assert (tmp_path / "episodes" / "soir" / "2026-08-14.json").exists()
    assert (tmp_path / "cover.png").exists() and (tmp_path / "cover-soir.png").exists()


async def test_generate_skips_when_empty(tmp_path, monkeypatch):
    async def _empty_fetch(show, *, now=None, seen=None, client=None, ranker=None):
        return FetchResult(selected=[], all_keys=[])

    monkeypatch.setattr(generate, "fetch_items", _empty_fetch)
    config = Config(shows=[Show(id="matin", sources=[Source(name="T", url="https://ex.com/rss")])])
    result = await generate_episode(config, config.show(), tmp_path, now=datetime(2026, 8, 14, tzinfo=PARIS))
    assert not result.ok
    assert "Aucun nouvel article" in result.reason


def test_seen_roundtrip_and_legacy(tmp_path):
    show = Show(id="matin")
    save_seen(tmp_path, show, {"a", "b"})
    assert load_seen(tmp_path, show) == {"a", "b"}
    # héritage de l'ancien format mono-émission
    (tmp_path / "seen.json").write_text(json.dumps(["legacy"]), encoding="utf-8")
    (tmp_path / "seen-matin.json").unlink()
    assert load_seen(tmp_path, show) == {"legacy"}


def test_cover_generated_once(tmp_path):
    from PIL import Image

    cover = generate.make_cover("Mon Podcast Perso", tmp_path / "cover.png")
    assert cover.exists()
    with Image.open(cover) as img:
        assert img.size == (1400, 1400)
