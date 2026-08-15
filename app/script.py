"""Construction du script de l'épisode (mode déterministe).

Structure : intro (éphéméride) → flash des titres → météo → brèves →
à lire (liste de lecture) → outro. Le mode IA (app/ai.py) produit la même
structure avec plus de naturel ; ce module reste le repli garanti.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Show
from .sources import FeedItem, clean_html

PARIS = ZoneInfo("Europe/Paris")

ORDINALS_FEM = [
    "Première", "Deuxième", "Troisième", "Quatrième", "Cinquième",
    "Sixième", "Septième", "Huitième", "Neuvième", "Dixième",
]


def format_date_fr(now: datetime) -> str:
    """Date parlée en français : « jeudi 14 août »."""
    days = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    months = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    local = now.astimezone(PARIS)
    return f"{days[local.weekday()]} {local.day} {months[local.month - 1]}"


def _ordinal_fem(n: int) -> str:
    if 1 <= n <= len(ORDINALS_FEM):
        return ORDINALS_FEM[n - 1]
    return f"Brève {n}"


@dataclass
class Segment:
    """Un bloc de texte lu, avec son débit et (option) son locuteur."""

    kind: str  # intro | headlines | meteo | brief | reading | outro
    text: str
    rate: str  # débit edge-tts, ex. "+4%"
    speaker: str | None = None  # "co" = 2ᵉ voix (mode dialogue)


def episode_title(show: Show, now: datetime) -> str:
    """Titre affiché dans le lecteur : « Mon Briefing — jeudi 14 août ».

    Le titre de l'émission en préfixe : sans lui, toutes les émissions d'un
    même compte sortaient sous le même intitulé dans le lecteur de podcast.
    """
    return f"{show.title} — {format_date_fr(now)}"


def episode_description(items: list[FeedItem]) -> str:
    """Description de l'épisode : la liste des titres traités."""
    return " • ".join(item.title for item in items)


def build_script(
    show: Show,
    items: list[FeedItem],
    *,
    now: datetime | None = None,
    weather: object | None = None,  # app.weather.Weather (typage souple pour tests)
    weather_line: str = "",
    ephemeris_line: str = "",
    reading_items: list | None = None,
) -> list[Segment]:
    """Construit les segments du script à partir des éléments du jour."""
    from .weather import weather_text

    now = now or datetime.now(tz=PARIS)
    date_str = format_date_fr(now)
    segments: list[Segment] = []

    intro = (
        f"Bonjour, et bienvenue dans {show.title}. Nous sommes le {date_str}. "
        f"{ephemeris_line} Voici l'essentiel de l'actualité en quelques minutes."
    )
    segments.append(Segment("intro", " ".join(intro.split()), show.intro_rate))

    headlines = items[: show.num_headlines]
    briefs = items[: show.num_briefs]

    if headlines:
        flash = " ".join(f"{item.title}. " for item in headlines)
        segments.append(
            Segment("headlines", f"Voici d'abord les titres du jour. {flash}", show.brief_rate)
        )

    if weather is not None:
        segments.append(Segment("meteo", weather_text(weather), show.intro_rate))
    elif weather_line:
        segments.append(Segment("meteo", weather_line, show.intro_rate))

    for idx, item in enumerate(briefs, start=1):
        summary = clean_html(item.summary, show.max_brief_chars)
        body = f"{item.title}. {summary}" if summary else item.title
        segments.append(
            Segment("brief", f"{_ordinal_fem(idx)} brève : {body}", show.brief_rate)
        )

    if reading_items:
        parts = ["Et pour finir, ta liste de lecture."]
        for item in reading_items:
            extract = (getattr(item, "text", "") or "")[:400]
            parts.append(f"{item.title}. {extract}".strip())
        segments.append(Segment("reading", " ".join(parts), show.brief_rate))

    segments.append(
        Segment(
            "outro",
            f"Voilà pour l'essentiel de ce {date_str}. À demain pour une nouvelle édition "
            f"de {show.title}. Bonne journée !",
            show.intro_rate,
        )
    )
    return segments


def script_text(segments: list[Segment]) -> str:
    """Texte complet (aperçu / éditeur de script)."""
    return "\n\n".join(segment.text for segment in segments)
