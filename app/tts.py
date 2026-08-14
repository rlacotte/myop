"""Synthèse vocale via Edge TTS et assemblage du MP3 final."""

from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts
from pydub import AudioSegment

from .script import Segment

# Nombre de segments synthétisés en parallèle (restons courtois avec le service)
_CONCURRENCY = 3
# Pause (ms) entre les segments pour un rythme naturel
_GAP_MS = 400

# Voix françaises proposées dans le dashboard (secours si l'appel réseau échoue)
FRENCH_VOICES = [
    {"ShortName": "fr-FR-DeniseNeural", "Gender": "Female", "label": "Denise (FR)"},
    {"ShortName": "fr-FR-RemyMultilingualNeural", "Gender": "Male", "label": "Rémy (FR)"},
    {"ShortName": "fr-FR-HenriNeural", "Gender": "Male", "label": "Henri (FR)"},
    {"ShortName": "fr-FR-VivienneMultilingualNeural", "Gender": "Female", "label": "Vivienne (FR)"},
    {"ShortName": "fr-CA-SylvieNeural", "Gender": "Female", "label": "Sylvie (Québec)"},
    {"ShortName": "fr-CA-AntoineNeural", "Gender": "Male", "label": "Antoine (Québec)"},
    {"ShortName": "fr-BE-CharlineNeural", "Gender": "Female", "label": "Charline (Belgique)"},
    {"ShortName": "fr-CH-ArianeNeural", "Gender": "Female", "label": "Ariane (Suisse)"},
]

SAMPLE_TEXT = "Bonjour ! Voici un extrait de cette voix. Elle lira ton briefing chaque matin."


async def list_voices() -> list[dict]:
    """Voix françaises disponibles (liste Edge TTS en direct, secours statique)."""
    try:
        voices = await edge_tts.list_voices()
        french = [v for v in voices if v.get("Locale", "").startswith("fr-")]
        if french:
            return [
                {
                    "ShortName": v["ShortName"],
                    "Gender": v.get("Gender", ""),
                    "label": f"{v.get('LocalName', v['ShortName'])} ({v['Locale']})",
                }
                for v in french
            ]
    except Exception:
        pass
    return FRENCH_VOICES


async def synthesize_segment(text: str, voice: str, rate: str, out: Path) -> None:
    """Synthétise un segment en MP3 (surchargeable dans les tests)."""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out))


async def synthesize(
    segments: list[Segment], voice: str, out_path: Path
) -> tuple[Path, int]:
    """Synthétise tous les segments puis les assemble en un seul MP3.

    Retourne (chemin du fichier, durée en secondes).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_path.parent / f".tts-{out_path.stem}"
    tmp_dir.mkdir(exist_ok=True)

    # Synthèse parallèle des segments
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def _one(index: int, segment: Segment) -> Path:
        part = tmp_dir / f"{index:03d}.mp3"
        async with semaphore:
            await synthesize_segment(segment.text, voice, segment.rate, part)
        return part

    parts = await asyncio.gather(*[_one(i, s) for i, s in enumerate(segments)])

    # Assemblage avec pauses entre segments
    silence = AudioSegment.silent(duration=_GAP_MS)
    audio = AudioSegment.empty()
    for part in parts:
        seg = AudioSegment.from_file(part)
        audio += seg + silence
    audio.export(out_path, format="mp3", bitrate="48k")

    # Nettoyage des fichiers temporaires
    for part in parts:
        part.unlink(missing_ok=True)
    tmp_dir.rmdir()

    return out_path, len(audio) // 1000


async def voice_preview(voice: str, out_path: Path) -> Path:
    """Extrait court pour écouter une voix dans le dashboard."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    await synthesize_segment(SAMPLE_TEXT, voice, "+0%", out_path)
    return out_path
