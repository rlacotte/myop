"""Configuration du podcast : modèle pydantic ↔ config.yaml.

Un « show » est une émission distincte (ex : un briefing le matin, un magazine
tech le soir). Chaque show a ses sources, sa voix, son heure et son flux RSS.
Les réglages IA, audio et GitHub sont partagés.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class Source(BaseModel):
    """Une source d'actualité : un flux RSS."""

    name: str
    url: str


class Show(BaseModel):
    """Une émission quotidienne, avec son flux RSS dédié."""

    id: str = "matin"  # slug : episodes/<id>/, podcast-<id>.xml
    title: str = "Mon Briefing"
    description: str = "L'essentiel de l'actualité, résumé chaque matin en quelques minutes."
    enabled: bool = True

    delivery_hour: str = "07:30"  # heure de livraison (Paris)

    # Voix (nom Edge TTS ou identifiant ElevenLabs si voice_provider = elevenlabs)
    voice: str = "fr-FR-DeniseNeural"
    voice_co: str | None = None  # 2ᵉ voix : active le mode dialogue (IA)
    intro_rate: str = "-8%"
    brief_rate: str = "+4%"

    # Contenu
    num_headlines: int = Field(default=12, ge=1, le=30)
    num_briefs: int = Field(default=5, ge=0, le=10)
    max_brief_chars: int = Field(default=450, ge=100, le=2000)
    max_per_source: int = Field(default=3, ge=1, le=10)

    # Segments riches
    weather_city: str | None = None  # ex : "Paris" → segment météo
    ephemeris: bool = True  # jour férié / semaine / lune dans l'intro

    sources: list[Source] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        value = value.strip().lower().replace(" ", "-")
        if not value or not value.replace("-", "").isalnum():
            raise ValueError("identifiant de show : lettres, chiffres et tirets uniquement")
        return value


class AIConfig(BaseModel):
    """Rédaction du script par IA via OpenRouter (optionnelle)."""

    enabled: bool = False
    model: str = "google/gemini-3.6-flash"
    key_file: str = ".openrouter_api_key"  # racine du repo, non versionné
    # Ton de l'émission (injecté dans la consigne système)
    persona: str = "rédacteur en chef d'un flash radio matinal : clair, vif, chaleureux, jamais sensationnaliste"
    # Consigne système entièrement personnalisée (prioritaire sur persona)
    system_prompt: str | None = None


class AudioConfig(BaseModel):
    """Habillage sonore et confort d'écoute."""

    jingle: bool = True  # jingle d'intro/outro + transitions entre sections
    chapters: bool = True  # chapitrage ID3 (titres navigables dans le lecteur)
    provider: str = "edge"  # moteur de voix : edge (gratuit) | elevenlabs (premium)
    elevenlabs_key_file: str = ".elevenlabs_api_key"  # non versionné


class ReadingConfig(BaseModel):
    """Liste de lecture : des articles à écouter dans l'épisode."""

    enabled: bool = True
    max_items: int = Field(default=3, ge=0, le=5)  # articles lus par épisode


class AnalyticsConfig(BaseModel):
    """Statistiques d'écoute (option, ex. GoatCounter — respectueux de la vie privée)."""

    url: str | None = None  # ex. https://monpodcast.goatcounter.com/count


class GitHubConfig(BaseModel):
    """Réglages de livraison GitHub (remplis par `myop setup`)."""

    repo: str | None = None  # "owner/repo"
    pages_base: str | None = None  # "https://owner.github.io/repo/"
    private: bool = False


class Config(BaseModel):
    """Configuration complète : émissions + réglages partagés."""

    language: str = "fr-FR"
    author: str = "Moi"
    email: str = "moi@example.com"
    category: str = "News"  # catégorie iTunes (News, Technology, Sports…)

    skip_if_empty: bool = True  # pas d'épisode s'il n'y a rien de nouveau

    shows: list[Show] = Field(default_factory=list)
    ai: AIConfig = Field(default_factory=AIConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    reading: ReadingConfig = Field(default_factory=ReadingConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)

    def show(self, show_id: str | None = None) -> Show:
        """Show par identifiant (parmi tous), sinon le premier activé."""
        if show_id is not None:
            for show in self.shows:
                if show.id == show_id:
                    return show
            raise KeyError(f"émission inconnue : {show_id}")
        enabled = [s for s in self.shows if s.enabled]
        pool = enabled or self.shows
        if not pool:
            raise KeyError("aucune émission configurée")
        return pool[0]

    def feed_url(self, show: Show | None = None) -> str | None:
        """URL du flux RSS d'une émission (la 1ʳᵉ est servie sur podcast.xml)."""
        base = self.github.pages_base
        if not base:
            return None
        base = base.rstrip("/") + "/"
        show = show or (self.shows[0] if self.shows else None)
        if show is None:
            return None
        first = next((s for s in self.shows if s.enabled), None)
        if show.id == (first.id if first else None):
            return f"{base}podcast.xml"
        return f"{base}podcast-{show.id}.xml"


DEFAULT_SOURCES = [
    Source(name="Le Monde — À la une", url="https://www.lemonde.fr/rss/une.xml"),
    Source(name="franceinfo — Titres", url="https://www.francetvinfo.fr/titres.rss"),
    Source(name="Europe 1 — Actualités", url="https://www.europe1.fr/rss.xml"),
    Source(name="NextINpact — Numérique", url="https://www.nextinpact.com/rss"),
    Source(name="France Culture — Idées", url="https://www.radiofrance.fr/franceculture/rss"),
]


def _migrate(data: dict) -> dict:
    """Convertit une config v1 (champs à la racine) en config v2 (shows[])."""
    if data.get("shows"):
        return data
    legacy_keys = [
        "title", "description", "voice", "intro_rate", "brief_rate", "num_headlines",
        "num_briefs", "max_brief_chars", "max_per_source", "delivery_hour", "sources",
    ]
    if not any(key in data for key in legacy_keys):
        return data
    show = {"id": "matin"}
    for key in legacy_keys:
        if key in data:
            show[key if key != "sources" else "sources"] = data.pop(key)
    data["shows"] = [show]
    return data


def load_config(path: Path | None = None) -> Config:
    """Charge la config ; valeurs par défaut si le fichier est absent."""
    path = path or CONFIG_PATH
    if not path.exists():
        return Config(shows=[Show(sources=list(DEFAULT_SOURCES))])
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = _migrate(data)
    if not data.get("shows"):
        data["shows"] = [{"sources": [s.model_dump() for s in DEFAULT_SOURCES]}]
    return Config.model_validate(data)


def save_config(config: Config, path: Path | None = None) -> None:
    """Écrit la config en YAML (ordre des champs préservé pour rester lisible)."""
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def write_default_config(path: Path | None = None) -> Config:
    """Crée config.yaml avec les valeurs par défaut (si absent)."""
    path = path or CONFIG_PATH
    if not path.exists():
        config = Config(shows=[Show(sources=list(DEFAULT_SOURCES))])
        save_config(config, path)
        return config
    return load_config(path)
