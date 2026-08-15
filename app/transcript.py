"""Transcription de l'épisode : texte lisible et WebVTT synchronisé.

Le script est déjà écrit et l'assemblage audio connaît les bornes de chaque
segment : la transcription ne coûte qu'une écriture de fichier. Elle rend
l'épisode lisible sans écouter, indexable, et accessible aux lecteurs qui
gèrent la balise <podcast:transcript>.
"""

from __future__ import annotations

from pathlib import Path

from .script import Segment

SPEAKER_LABELS = {"host": "Voix 1", "co": "Voix 2"}


def _timestamp(milliseconds: int) -> str:
    """« 00:01:23.400 », format imposé par WebVTT."""
    seconds, ms = divmod(max(int(milliseconds), 0), 1000)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def build_vtt(segments: list[Segment], chapters: list[dict]) -> str:
    """WebVTT : une réplique par segment, calée sur l'audio produit."""
    lines = ["WEBVTT", ""]
    for index, (segment, chapter) in enumerate(zip(segments, chapters), start=1):
        speaker = SPEAKER_LABELS.get(segment.speaker or "")
        text = f"<v {speaker}>{segment.text}" if speaker else segment.text
        lines += [
            str(index),
            f"{_timestamp(chapter['start_ms'])} --> {_timestamp(chapter['end_ms'])}",
            text,
            "",
        ]
    return "\n".join(lines)


def build_text(title: str, segments: list[Segment]) -> str:
    """Version lisible, servie depuis la page publique."""
    lines = [title, "=" * len(title), ""]
    for segment in segments:
        speaker = SPEAKER_LABELS.get(segment.speaker or "")
        lines.append(f"{speaker} — {segment.text}" if speaker else segment.text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_transcript(
    title: str, segments: list[Segment], chapters: list[dict], episode_path: Path
) -> bool:
    """Écrit « <épisode>.vtt » et « <épisode>.txt ». Faux si rien à écrire.

    Sans chapitres (chapitrage désactivé) le VTT n'a pas de bornes fiables :
    on se contente alors du texte.
    """
    if not segments:
        return False
    episode_path.parent.mkdir(parents=True, exist_ok=True)
    episode_path.with_suffix(".txt").write_text(
        build_text(title, segments), encoding="utf-8"
    )
    if len(chapters) != len(segments):
        return False
    episode_path.with_suffix(".vtt").write_text(
        build_vtt(segments, chapters), encoding="utf-8"
    )
    return True
