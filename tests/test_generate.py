"""Test d'intégration du pipeline (collecte et TTS simulés)."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import generate
from app.config import Config, Source
from app.generate import generate_episode
from app.sources import FeedItem, FetchResult
from tests.test_tts import _fake_segment

PARIS = ZoneInfo("Europe/Paris")


async def _fake_fetch(config, *, now=None, seen=None, client=None):
    items = [
        FeedItem(
            title=f"Actu {i}",
            url=f"https://ex.com/{i}",
            published=now - timedelta(hours=1),
            summary=f"Résumé de l'actu {i}.",
            source_name="Test",
            guid=f"g{i}",
        )
        for i in range(3)
    ]
    return FetchResult(selected=items, all_keys=[item.key for item in items])


async def test_generate_episode_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "fetch_items", _fake_fetch)
    monkeypatch.setattr(generate, "synthesize", _fake_synthesize)

    config = Config(
        title="Podcast Test",
        num_headlines=3,
        num_briefs=2,
        sources=[Source(name="Test", url="https://ex.com/rss")],
        github={"pages_base": "https://me.github.io/myop/"},
    )
    now = datetime(2026, 8, 14, 7, 30, tzinfo=PARIS)

    result = await generate_episode(config, tmp_path, now=now)

    assert result.ok
    assert result.episode_id == "2026-08-14"
    assert result.episode_path.exists()
    assert result.titles == ["Actu 0", "Actu 1", "Actu 2"]

    # Métadonnées, historique, flux et pochette produits
    meta = json.loads((tmp_path / "episodes" / "2026-08-14.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Briefing du vendredi 14 août"
    assert meta["duration"] == 3  # 5 segments simulés (intro + titres + 2 brèves + outro)
    seen = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
    assert set(seen) == {"https://ex.com/0", "https://ex.com/1", "https://ex.com/2"}
    assert (tmp_path / "podcast.xml").exists()
    assert (tmp_path / "cover.png").exists()
    assert (tmp_path / "index.html").exists()
    xml = (tmp_path / "podcast.xml").read_text(encoding="utf-8")
    assert "https://me.github.io/myop/episodes/2026-08-14.mp3" in xml


async def _fake_synthesize(segments, voice, out_path):
    from pydub import AudioSegment

    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio = AudioSegment.silent(duration=len(segments) * 600, frame_rate=24000)
    audio.export(out_path, format="mp3", bitrate="48k")
    return out_path, len(audio) // 1000


async def test_generate_skips_when_empty(tmp_path, monkeypatch):
    async def _empty_fetch(config, *, now=None, seen=None, client=None):
        return FetchResult(selected=[], all_keys=[])

    monkeypatch.setattr(generate, "fetch_items", _empty_fetch)
    config = Config(sources=[Source(name="Test", url="https://ex.com/rss")])

    result = await generate_episode(config, tmp_path, now=datetime(2026, 8, 14, tzinfo=PARIS))
    assert not result.ok
    assert "Aucun nouvel article" in result.reason
    assert not list((tmp_path / "episodes").glob("*.mp3"))


def test_cover_generated_once(tmp_path):
    from PIL import Image

    config = Config(title="Mon Podcast Perso")
    cover = generate.make_cover(config, tmp_path / "cover.png")
    assert cover.exists()
    with Image.open(cover) as img:
        assert img.size == (1400, 1400)
