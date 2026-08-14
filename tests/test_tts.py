"""Tests audio : assemblage TTS (simulé), jingle, chapitrage, providers."""

from pathlib import Path

import httpx
import pytest
from pydub import AudioSegment

from app import tts
from app.config import Config, Show
from app.chapters import read_chapter_titles, write_chapters
from app.jingle import jingle_intro, jingle_outro, transition
from app.script import Segment


async def _fake_segment(config, text, voice, rate, out: Path) -> None:
    """Remplace la synthèse : silence de 300 ms (pas de réseau, durées exactes)."""
    AudioSegment.silent(duration=300, frame_rate=24000).export(out, format="wav")


@pytest.fixture
def no_jingle_config() -> Config:
    return Config(audio={"jingle": False, "chapters": False})


async def test_synthesize_concatenates_and_chapter_boundaries(tmp_path, monkeypatch, no_jingle_config):
    monkeypatch.setattr(tts, "synthesize_segment", _fake_segment)
    show = Show(id="t", voice="fr-FR-DeniseNeural")
    segments = [
        Segment("intro", "Bonjour, texte d'introduction.", "+0%"),
        Segment("brief", "Première brève.", "+4%"),
        Segment("brief", "Deuxième brève.", "+4%"),
        Segment("outro", "À demain !", "+0%"),
    ]
    out = tmp_path / "episode.mp3"
    result = await tts.synthesize(segments, show, no_jingle_config, out)

    assert result.path == out and out.exists()
    assert 1 <= result.duration_seconds <= 3
    audio = AudioSegment.from_file(out)
    assert audio.frame_rate == 24000
    # Chapitres : un par segment, titres humains, bornes croissantes
    assert [c["title"] for c in result.chapters] == ["Intro", "Brève 1", "Brève 2", "Conclusion"]
    assert result.chapters[0]["start_ms"] == 0
    assert all(
        result.chapters[i]["end_ms"] <= result.chapters[i + 1]["start_ms"]
        for i in range(len(result.chapters) - 1)
    )
    assert not list(tmp_path.glob(".tts-*"))


async def test_synthesize_with_jingle_and_dialogue(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "synthesize_segment", _fake_segment)
    config = Config(audio={"jingle": True, "chapters": False})
    show = Show(id="t", voice="fr-FR-DeniseNeural", voice_co="fr-FR-VivienneMultilingualNeural")
    segments = [
        Segment("intro", "Bonjour !", "-8%", speaker="host"),
        Segment("brief", "Première brève.", "+4%", speaker="co"),
        Segment("outro", "À demain !", "-8%"),
    ]
    out = tmp_path / "episode.mp3"
    result = await tts.synthesize(segments, show, config, out)

    # Le jingle rallonge l'épisode (~2,6 s d'intro + ~1,8 s d'outro)
    assert result.duration_seconds >= 4
    assert result.chapters[0]["start_ms"] >= 1300  # le 1ᵉʳ chapitre démarre après le jingle


def test_jingle_modules_produce_audio():
    for jingle in (jingle_intro(), jingle_outro(), transition()):
        assert isinstance(jingle, AudioSegment)
        assert len(jingle) > 100  # au moins 100 ms
    assert len(jingle_intro()) > 1200  # logo d'ouverture audible
    assert len(transition()) < 800  # discret


def test_chapters_written_and_readable(tmp_path):
    from pydub import AudioSegment

    mp3 = tmp_path / "e.mp3"
    AudioSegment.silent(duration=3000, frame_rate=24000).export(mp3, format="mp3")
    write_chapters(
        mp3,
        [
            {"title": "Intro", "start_ms": 0, "end_ms": 1500},
            {"title": "Brève 1", "start_ms": 1500, "end_ms": 3000},
        ],
    )
    assert read_chapter_titles(mp3) == ["Intro", "Brève 1"]


def test_speaker_voice_mapping():
    show = Show(id="t", voice="A", voice_co="B")
    segments = [Segment("intro", "x", "+0%"), Segment("brief", "y", "+0%", speaker="co")]
    assert tts._segment_voices(segments, show) == ["A", "B"]


async def test_elevenlabs_provider_dispatch(tmp_path, monkeypatch):
    """Provider elevenlabs → appel API (mocké) avec la clé."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    config = Config(audio={"provider": "elevenlabs"})
    captured = {}

    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        return httpx.Response(200, content=b"fake-audio", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    out = tmp_path / "seg.mp3"
    await tts.synthesize_segment(config, "Bonjour", "voice-id", "+0%", out)

    assert "elevenlabs.io" in captured["url"]
    assert captured["headers"]["xi-api-key"] == "test-key"
    assert out.read_bytes() == b"fake-audio"
