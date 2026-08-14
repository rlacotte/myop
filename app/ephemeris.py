"""Éphéméride : jours fériés français, semaine, phase de lune.

Tout est calculé hors ligne (algorithme de Meeus pour Pâques, cycle lunaire
synodique approché) — aucune dépendance réseau.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")

FIXED_HOLIDAYS = {
    (1, 1): "jour de l'An",
    (5, 1): "Fête du Travail",
    (5, 8): "Victoire 1945",
    (7, 14): "Fête nationale",
    (8, 15): "Assomption",
    (11, 1): "Toussaint",
    (11, 11): "Armistice 1918",
    (12, 25): "Noël",
}

MOON_PHASES = [
    ("nouvelle lune", 1.84566),
    ("premier croissant", 5.53699),
    ("premier quartier", 9.22831),
    ("lune gibbeuse croissante", 12.91963),
    ("pleine lune", 16.61096),
    ("lune gibbeuse décroissante", 20.30228),
    ("dernier quartier", 23.99361),
    ("dernier croissant", 27.68493),
]


def easter(year: int) -> date:
    """Dimanche de Pâques (algorithme de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def holiday_name(day: date) -> str | None:
    """Nom du jour férié, sinon None (inclut les fêtes mobiles)."""
    fixed = FIXED_HOLIDAYS.get((day.month, day.day))
    if fixed:
        return fixed
    easter_day = easter(day.year)
    mobile = {
        easter_day: "Pâques",
        easter_day + timedelta(days=1): "lundi de Pâques",
        easter_day + timedelta(days=39): "Ascension",
        easter_day + timedelta(days=49): "Pentecôte",
        easter_day + timedelta(days=50): "lundi de Pentecôte",
    }
    return mobile.get(day)


def moon_phase(day: date) -> str:
    """Phase lunaire approchée (cycle synodique 29,53 jours, référence 2000-01-06)."""
    known_new_moon = date(2000, 1, 6)
    cycle = 29.530588853
    age = ((day - known_new_moon).days % cycle) / cycle * 29.530588853
    return min(MOON_PHASES, key=lambda phase: abs(age - phase[1]))[0]


def week_number(day: date) -> int:
    """Numéro de semaine ISO."""
    return day.isocalendar()[1]


def ephemeris_text(now: datetime) -> str:
    """Phrase d'éphéméride pour l'intro : férié, semaine, lune si notable."""
    day = now.astimezone(PARIS).date()
    parts: list[str] = []

    holiday = holiday_name(day)
    if holiday:
        parts.append(f"aujourd'hui est férié : c'est {holiday}")

    week = week_number(day)
    if day.weekday() == 0:  # lundi : on situe la semaine
        parts.append(f"nous entamons la semaine {week}")
    elif not parts and day.weekday() == 6:
        parts.append(f"nous sommes dimanche, semaine {week}")

    phase = moon_phase(day)
    if phase == "pleine lune":
        parts.append("et c'est la pleine lune ce soir")
    elif phase == "nouvelle lune":
        parts.append("et c'est la nouvelle lune")

    if not parts:
        return ""
    return "Au passage, " + ", ".join(parts) + "."
