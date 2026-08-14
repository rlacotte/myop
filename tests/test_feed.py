"""Tests du flux RSS podcast : structure iTunes/enclosure, validité feedparser."""

import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser

from app.config import Config
from app.feed import build_feed, load_episode_metas, write_feed

BASE = "https://me.github.io/myop/"


def _write_episode(dist: Path, ep_id: str, published: datetime, size: int = 12345) -> dict:
    meta = {
        "id": ep_id,
        "title": f"Briefing du {ep_id}",
        "description": "Titre A • Titre B",
        "pubDate": published.isoformat(),
        "duration": 195,
        "size": size,
    }
    (dist / "episodes" / f"{ep_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return meta


def test_build_feed_full_itunes_structure(tmp_path):
    config = Config(title="Podcast Test", github={"pages_base": BASE})
    dist = tmp_path / "dist"
    (dist / "episodes").mkdir(parents=True)
    day1 = _write_episode(dist, "2026-08-13", datetime(2026, 8, 13, 7, 30, tzinfo=timezone.utc))
    day2 = _write_episode(dist, "2026-08-14", datetime(2026, 8, 14, 7, 30, tzinfo=timezone.utc))

    xml = build_feed(config, load_episode_metas(dist), BASE)
    parsed = feedparser.parse(xml)

    # Métadonnées du podcast
    assert parsed.feed.title == "Podcast Test"
    assert parsed.feed.language == "fr"
    assert parsed.feed.image.href == f"{BASE}cover.png"

    # Épisodes du plus récent au plus ancien, enclosure complète
    assert [e.id for e in parsed.entries] == ["myop-2026-08-14", "myop-2026-08-13"]
    entry = parsed.entries[0]
    enclosure = entry.enclosures[0]
    assert enclosure.href == f"{BASE}episodes/2026-08-14.mp3"
    assert enclosure.type == "audio/mpeg"
    assert enclosure.length == str(day2["size"])
    assert entry.published_parsed is not None  # date RFC 822 valide
    assert entry.itunes_duration == "3:15"  # 195 s

    # Tags iTunes présents dans le XML brut
    assert "itunes:author" in xml
    assert 'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"' in xml


def test_write_feed_uses_pages_base(tmp_path):
    config = Config(github={"pages_base": BASE})
    dist = tmp_path / "dist"
    (dist / "episodes").mkdir(parents=True)
    _write_episode(dist, "2026-08-14", datetime(2026, 8, 14, 7, 30, tzinfo=timezone.utc))

    out = write_feed(config, dist)
    assert out.exists()
    xml = out.read_text(encoding="utf-8")
    assert f"{BASE}episodes/2026-08-14.mp3" in xml


def test_write_feed_requires_pages_base(tmp_path):
    import pytest

    config = Config()  # pas de pages_base
    with pytest.raises(RuntimeError, match="myop setup"):
        write_feed(config, tmp_path)


def test_corrupt_meta_ignored(tmp_path):
    dist = tmp_path / "dist"
    (dist / "episodes").mkdir(parents=True)
    _write_episode(dist, "2026-08-14", datetime(2026, 8, 14, tzinfo=timezone.utc))
    (dist / "episodes" / "corrompu.json").write_text("{pas du json", encoding="utf-8")

    metas = load_episode_metas(dist)
    assert len(metas) == 1 and metas[0]["id"] == "2026-08-14"
