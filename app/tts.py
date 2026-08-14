"""Synthèse vocale et assemblage du MP3 final.

Deux moteurs de voix :
- edge (défaut, gratuit) : Edge TTS de Microsoft
- elevenlabs (premium) : API ElevenLabs, clé dans .elevenlabs_api_key

L'assemblage ajoute le jingle, les transitions entre sections et calcule
les bornes temporelles pour le chapitrage ID3.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts
import httpx
from pydub import AudioSegment

from .config import Config, Show
from .jingle import jingle_intro, jingle_outro, transition
from .script import Segment

# Nombre de segments synthétisés en parallèle (restons courtois avec les services)
_CONCURRENCY = 3
_GAP_MS = 400  # pause entre segments

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

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


def elevenlabs_key(config: Config) -> str | None:
    """Clé ElevenLabs (fichier non versionné ou variable d'environnement)."""
    import os

    key_file = Path(config.audio.elevenlabs_key_file)
    if not key_file.is_absolute():
        key_file = Path(__file__).resolve().parent.parent / key_file
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    return os.environ.get("ELEVENLABS_API_KEY") or None


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


async def _synth_edge(text: str, voice: str, rate: str, out: Path) -> None:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(out))


async def _synth_elevenlabs(
    text: str, voice_id: str, key: str, out: Path, *, rate: str = "+0%"
) -> None:
    """Synthèse ElevenLabs (le débit n'est pas réglable par requête)."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            ELEVENLABS_URL.format(voice_id=voice_id),
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        )
        resp.raise_for_status()
        out.write_bytes(resp.content)


async def synthesize_segment(
    config: Config, text: str, voice: str, rate: str, out: Path
) -> None:
    """Synthétise un segment (surchargeable dans les tests)."""
    if config.audio.provider == "elevenlabs":
        key = elevenlabs_key(config)
        if not key:
            raise RuntimeError("clé ElevenLabs absente (.elevenlabs_api_key)")
        await _synth_elevenlabs(text, voice, key, out, rate=rate)
    else:
        await _synth_edge(text, voice, rate, out)


class SynthResult:
    """Résultat d'assemblage : fichier, durée, chapitres (bornes en ms)."""

    def __init__(self, path: Path, duration_seconds: int, chapters: list[dict]):
        self.path = path
        self.duration_seconds = duration_seconds
        self.chapters = chapters


def _segment_voices(segments: list[Segment], show: Show) -> list[str]:
    """Voix de chaque segment : la 2ᵉ voix prend les segments « co ». """
    return [
        show.voice_co if (show.voice_co and s.speaker == "co") else show.voice
        for s in segments
    ]


def _chapter_title(segment: Segment, index: int) -> str:
    labels = {
        "intro": "Intro",
        "headlines": "Les titres",
        "meteo": "Météo",
        "brief": "Brèves",
        "reading": "À lire",
        "outro": "Conclusion",
    }
    base = labels.get(segment.kind, segment.kind)
    return base if segment.kind != "brief" else f"Brève {index}"


async def synthesize(
    segments: list[Segment], show: Show, config: Config, out_path: Path
) -> SynthResult:
    """Synthétise tous les segments puis les assemble en un seul MP3.

    Jingle d'intro/outro + transitions entre sections si activés.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_path.parent / f".tts-{out_path.stem}"
    tmp_dir.mkdir(exist_ok=True)

    semaphore = asyncio.Semaphore(_CONCURRENCY)
    voices = _segment_voices(segments, show)

    async def _one(index: int) -> Path:
        part = tmp_dir / f"{index:03d}.mp3"
        async with semaphore:
            await synthesize_segment(
                config, segments[index].text, voices[index], segments[index].rate, part
            )
        return part

    parts = await asyncio.gather(*[_one(i) for i in range(len(segments))])

    silence = AudioSegment.silent(duration=_GAP_MS)
    audio = AudioSegment.empty()
    chapters: list[dict] = []

    if config.audio.jingle:
        audio += jingle_intro()

    brief_index = 0
    for i, (part, segment) in enumerate(zip(parts, segments)):
        # Transition quand on change de section (sauf tout au début)
        if config.audio.jingle and audio.frame_width and i > 0 and segments[i - 1].kind != segment.kind:
            audio += transition()
        start_ms = len(audio)
        seg_audio = AudioSegment.from_file(part)
        audio += seg_audio + silence

        if segment.kind == "brief":
            brief_index += 1
        title = _chapter_title(segment, brief_index)
        chapters.append({"title": title, "start_ms": start_ms, "end_ms": len(audio) - _GAP_MS})

    if config.audio.jingle:
        start_ms = len(audio)
        audio += jingle_outro()
        if chapters:
            chapters[-1]["end_ms"] = start_ms

    audio.export(out_path, format="mp3", bitrate="48k")

    for part in parts:
        part.unlink(missing_ok=True)
    if tmp_dir.exists():
        tmp_dir.rmdir()

    return SynthResult(out_path, len(audio) // 1000, chapters)


async def voice_preview(voice: str, out_path: Path, config: Config | None = None) -> Path:
    """Extrait court pour écouter une voix dans le dashboard."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    config = config or Config()
    await synthesize_segment(config, SAMPLE_TEXT, voice, "+0%", out_path)
    return out_path
