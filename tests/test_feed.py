"""Tests des flux par show, de la page publique et de l'IA v2."""

import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import pytest

from app.ai import ai_script, build_user_prompt, parse_segments, system_prompt
from app.config import Config, Show, Source
from app.feed import build_feed, feed_filename, load_episode_metas, write_feed
from app.sources import FeedItem

BASE = "https://me.github.io/myop/"


def _write_episode(dist: Path, show_id: str, ep_id: str, published: datetime, size: int = 12345) -> dict:
    meta = {
        "id": ep_id,
        "title": f"Briefing du {ep_id}",
        "description": "Titre A • Titre B",
        "pubDate": published.isoformat(),
        "duration": 195,
        "size": size,
    }
    folder = dist / "episodes" / show_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{ep_id}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def test_build_feed_per_show(tmp_path):
    config = Config(shows=[Show(id="matin", title="Le Matin"), Show(id="soir", title="Le Soir")],
                    github={"pages_base": BASE})
    dist = tmp_path / "dist"
    _write_episode(dist, "matin", "2026-08-14", datetime(2026, 8, 14, 7, 30, tzinfo=timezone.utc))
    _write_episode(dist, "soir", "2026-08-14", datetime(2026, 8, 14, 19, 30, tzinfo=timezone.utc))

    xml_matin = build_feed(config, config.show("matin"), load_episode_metas(dist, "matin"), BASE)
    parsed = feedparser.parse(xml_matin)
    assert parsed.feed.title == "Le Matin"
    entry = parsed.entries[0]
    assert entry.enclosures[0].href == f"{BASE}episodes/matin/2026-08-14.mp3"
    assert entry.id == "myop-matin-2026-08-14"
    assert entry.itunes_duration == "3:15"

    xml_soir = build_feed(config, config.show("soir"), load_episode_metas(dist, "soir"), BASE)
    parsed_soir = feedparser.parse(xml_soir)
    assert parsed_soir.feed.title == "Le Soir"
    assert parsed_soir.entries[0].enclosures[0].href == f"{BASE}episodes/soir/2026-08-14.mp3"


def test_feed_filename_first_show_canonical(tmp_path):
    config = Config(shows=[Show(id="matin"), Show(id="soir")])
    assert feed_filename(config, config.show("matin")) == "podcast.xml"
    assert feed_filename(config, config.show("soir")) == "podcast-soir.xml"


def test_write_feed_and_index(tmp_path):
    config = Config(
        shows=[Show(id="matin", title="Mon Show")],
        github={"pages_base": BASE},
    )
    dist = tmp_path / "dist"
    _write_episode(dist, "matin", "2026-08-14", datetime(2026, 8, 14, tzinfo=timezone.utc))

    out = write_feed(config, config.show(), dist)
    assert out.name == "podcast.xml"
    xml = out.read_text(encoding="utf-8")
    assert f"{BASE}episodes/matin/2026-08-14.mp3" in xml

    from app.feed import write_index

    write_index(config, dist)
    page = (dist / "index.html").read_text(encoding="utf-8")
    assert "overcast.fm" in page  # bouton one-tap Overcast
    assert "podcasts://" in page  # bouton Apple Podcasts
    assert "pktc://" in page  # bouton Pocket Casts
    assert "MYOP" in page


def test_write_feed_requires_pages_base(tmp_path):
    config = Config(shows=[Show(id="matin")])  # pas de pages_base
    with pytest.raises(RuntimeError, match="myop setup"):
        write_feed(config, config.show(), tmp_path)


def test_legacy_matin_layout_still_read(tmp_path):
    dist = tmp_path / "dist"
    (dist / "episodes").mkdir(parents=True)
    (dist / "episodes" / "old.json").write_text(
        json.dumps({"id": "2026-08-01", "title": "T", "description": "", "pubDate": "2026-08-01T07:00:00+02:00", "duration": 60, "size": 1}),
        encoding="utf-8",
    )
    assert load_episode_metas(dist, "matin")[0]["id"] == "2026-08-01"


# ------------------------------------------------------------------ IA v2 ---

AI_RESPONSE = {
    "segments": [
        {"kind": "intro", "text": "Bonjour, voici votre briefing du vendredi 14 août."},
        {"kind": "meteo", "text": "Côté météo, entre 14 et 26 degrés aujourd'hui."},
        {"kind": "brief", "text": "Première brève, l'actu un en détail."},
        {"kind": "outro", "text": "Voilà pour aujourd'hui, à demain !"},
    ]
}


@pytest.fixture
def ai_config() -> Config:
    return Config(
        shows=[Show(id="t", voice="fr-FR-DeniseNeural")],
        ai={"enabled": True, "model": "google/gemini-3.6-flash", "key_file": ".absent-key",
            "persona": "test persona"},
    )


def make_item(title: str) -> FeedItem:
    return FeedItem(title=title, url=f"https://ex.com/{title}", published=None,
                    summary="", source_name="Test", guid=f"g-{title}")


def test_system_prompt_uses_persona(ai_config):
    assert "test persona" in system_prompt(ai_config)
    ai_config.ai.system_prompt = "Consigne libre"
    assert system_prompt(ai_config) == "Consigne libre"


def test_user_prompt_includes_context(ai_config, now):
    show = ai_config.show()
    prompt = build_user_prompt(
        show, [make_item("Actu un")], now,
        weather_line="entre 14 et 26 degrés", ephemeris_line="c'est férié",
        reading_items=[type("R", (), {"title": "Article lu", "text": "Contenu."})()],
    )
    assert "vendredi 14 août" in prompt
    assert "Météo du jour" in prompt and "26 degrés" in prompt
    assert "Liste de lecture" in prompt and "Article lu" in prompt
    assert '(kind "meteo")' in prompt


def test_user_prompt_dialogue_mode(ai_config, now):
    show = ai_config.show()
    show.voice_co = "fr-FR-VivienneMultilingualNeural"
    prompt = build_user_prompt(show, [make_item("Actu")], now)
    assert '"speaker"' in prompt and "host" in prompt and '"co"' in prompt


def test_parse_segments_with_speakers(ai_config):
    show = ai_config.show()
    show.voice_co = "fr-FR-VivienneMultilingualNeural"
    payload = {
        "segments": [
            {"kind": "intro", "text": "Bonjour !", "speaker": "host"},
            {"kind": "brief", "text": "Une brève.", "speaker": "co"},
            {"kind": "outro", "text": "À demain !"},
        ]
    }
    segments = parse_segments(show, json.dumps(payload))
    assert [s.speaker for s in segments] == ["host", "co", None]

    # Sans 2ᵉ voix configurée, le speaker "co" est ignoré (rendu sur la voix principale)
    show.voice_co = None
    segments = parse_segments(show, json.dumps(payload))
    assert [s.speaker for s in segments] == ["host", None, None]


def test_parse_segments_rejects_garbage(ai_config):
    show = ai_config.show()
    assert parse_segments(show, "désolé, je ne peux pas") is None
    assert parse_segments(show, '{"segments": []}') is None


async def test_ai_script_sends_persona_and_context(ai_config, now, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(AI_RESPONSE)}}]})

    show = ai_config.show()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        segments = await ai_script(
            show, ai_config, [make_item("Actu")], now=now,
            weather_line="entre 14 et 26 degrés", client=client,
        )
    assert segments is not None
    assert captured["auth"] == "Bearer test-key"
    assert "test persona" in captured["payload"]["messages"][0]["content"]
    assert "Météo du jour" in captured["payload"]["messages"][1]["content"]
