"""Habillage sonore : jingle d'intro/outro et transitions, 100 % synthétisés.

Aucun fichier audio à fournir — un logo musical pentatonique est généré par
oscillateurs (pydub) et mixé à l'épisode.
"""

from __future__ import annotations

from pydub import AudioSegment
from pydub.effects import normalize
from pydub.generators import Sine

# Gamme pentatonique de La majeur (Hz) — chaleureuse, universelle
_A = 220.0
NOTES = {"A2": _A / 2, "A3": _A, "C#4": 277.18, "E4": 329.63, "F#4": 369.99, "A4": 440.0, "C#5": 554.37, "E5": 659.26}


def _note(freq: float, duration_ms: int, volume_db: float = -16) -> AudioSegment:
    """Une note avec enveloppe percussive (attaque franche, déclin doux)."""
    tone = Sine(freq=freq).to_audio_segment(duration=duration_ms, volume=volume_db)
    fade_ms = min(80, duration_ms // 4)
    return tone.fade_in(6).fade_out(duration_ms - fade_ms)


def _chord(freqs: list[float], duration_ms: int, volume_db: float = -22) -> AudioSegment:
    """Un accord : superposition de notes, enveloppe douce."""
    chord = AudioSegment.silent(duration=duration_ms)
    for freq in freqs:
        tone = Sine(freq=freq).to_audio_segment(duration=duration_ms, volume=volume_db)
        chord = chord.overlay(tone)
    return chord.fade_in(20).fade_out(200)


def jingle_intro() -> AudioSegment:
    """Logo d'ouverture (~2,6 s) : arpège montant + accord final tenu."""
    sequence = ["A3", "C#4", "E4", "F#4", "A4", "C#5"]
    part = AudioSegment.silent(duration=0)
    step = 150
    for i, name in enumerate(sequence):
        note = _note(NOTES[name], 450)
        part = part.append(note, crossfade=0) if i == 0 else part.overlay(note, position=i * step)
    final = _chord([NOTES["A3"], NOTES["E4"], NOTES["C#5"]], 900, volume_db=-24)
    jingle = (part + final).fade_out(400)
    return normalize(jingle, headroom=6)


def jingle_outro() -> AudioSegment:
    """Logo de clôture (~1,8 s) : arpège descendant, accord final bas."""
    sequence = ["E5", "C#5", "A4", "F#4"]
    part = AudioSegment.silent(duration=0)
    for i, name in enumerate(sequence):
        note = _note(NOTES[name], 380)
        part = part.append(note, crossfade=0) if i == 0 else part.overlay(note, position=i * 140)
    final = _chord([NOTES["A2"], NOTES["E4"]], 700, volume_db=-24)
    return normalize((part + final).fade_out(350), headroom=6)


def transition() -> AudioSegment:
    """Mini interstice (~0,5 s) entre les sections : deux notes discrètes."""
    first = _note(NOTES["E4"], 160, volume_db=-30)
    second = _note(NOTES["A4"], 300, volume_db=-30)
    return (first + second).fade_out(150)
