"""Rédaction du script de l'épisode à partir des articles sélectionnés.

Structure : intro datée → flash des titres → brèves détaillées → outro.
Le texte est 100 % déterministe (aucune IA requise).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from zoneinfo import ZoneInfo

from .config import Config
from .sources import FeedItem, clean_html

PARIS = ZoneInfo("Europe/Paris")

ORDINALS_FEM = [
    "Première",
    "Deuxième",
    "Troisième",
    "Quatrième",
    "Cinquième",
    "Sixième",
    "Septième",
    "Huitième",
    "Neuvième",
    "Dixième",
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
    """« Première », « Deuxième »… (au-delà de 10 : « Brève 11 »)."""
    if 1 <= n <= len(ORDINALS_FEM):
        return ORDINALS_FEM[n - 1]
    return f"Brève {n}"


@dataclass
class Segment:
    """Un bloc de texte lu avec son propre débit."""

    kind: str  # intro | headlines | brief | outro
    text: str
    rate: str  # débit edge-tts, ex. "+4%"


def episode_title(now: datetime) -> str:
    """Titre affiché dans le lecteur : « Briefing du jeudi 14 août »."""
    return f"Briefing du {format_date_fr(now)}"


def episode_description(items: list[FeedItem]) -> str:
    """Description de l'épisode : la liste des titres traités."""
    return " • ".join(item.title for item in items)


def build_script(config: Config, items: list[FeedItem], *, now: datetime | None = None) -> list[Segment]:
    """Construit les segments du script à partir des items sélectionnés."""
    now = now or datetime.now(tz=PARIS)
    date_str = format_date_fr(now)
    segments: list[Segment] = []

    segments.append(
        Segment(
            "intro",
            f"Bonjour, et bienvenue dans {config.title}. Nous sommes le {date_str}. "
            f"Voici l'essentiel de l'actualité en quelques minutes.",
            config.intro_rate,
        )
    )

    headlines = items[: config.num_headlines]
    briefs = items[: config.num_briefs]

    if headlines:
        flash = " ".join(f"{item.title}. " for item in headlines)
        segments.append(
            Segment("headlines", f"Voici d'abord les titres du jour. {flash}", config.brief_rate)
        )

    for idx, item in enumerate(briefs, start=1):
        summary = clean_html(item.summary, config.max_brief_chars)
        body = f"{item.title}. {summary}" if summary else item.title
        segments.append(
            Segment("brief", f"{_ordinal_fem(idx)} brève : {body}", config.brief_rate)
        )

    segments.append(
        Segment(
            "outro",
            f"Voilà pour l'essentiel de ce {date_str}. À demain pour une nouvelle édition "
            f"de {config.title}. Bonne journée !",
            config.intro_rate,
        )
    )
    return segments


def script_text(segments: list[Segment]) -> str:
    """Texte complet (aperçu / debug)."""
    return "\n\n".join(segment.text for segment in segments)
