"""Tests de l'assemblage audio (TTS simulé, concaténation réelle via ffmpeg)."""

from pathlib import Path

from pydub import AudioSegment

from app import tts
from app.script import Segment


async def _fake_segment(text: str, voice: str, rate: str, out: Path) -> None:
    """Remplace edge-tts : écrit un silence de 300 ms (pas de réseau, pas de
    quantification MP3 — en WAV pour des durées exactes)."""
    AudioSegment.silent(duration=300, frame_rate=24000).export(out, format="wav")


async def test_synthesize_concatenates_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "synthesize_segment", _fake_segment)
    segments = [
        Segment("intro", "Bonjour, texte d'introduction.", "+0%"),
        Segment("brief", "Première brève.", "+4%"),
        Segment("outro", "À demain !", "+0%"),
    ]
    out = tmp_path / "episode.mp3"
    path, seconds = await tts.synthesize(segments, "fr-FR-DeniseNeural", out)

    assert path == out and out.exists()
    # 3 segments × 300 ms + 3 pauses de 400 ms = 2,1 s (tolérance frame MP3)
    assert 2 <= seconds <= 3
    audio = AudioSegment.from_file(out)
    assert audio.frame_rate == 24000
    # Fichiers temporaires nettoyés
    assert not list(tmp_path.glob(".tts-*"))
