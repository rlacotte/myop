"""Configuration du podcast : modèle pydantic ↔ config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class Source(BaseModel):
    """Une source d'actualité : un flux RSS."""

    name: str
    url: str
    priority: int = 1  # plus élevé = privilégiée lors de la sélection


class GitHubConfig(BaseModel):
    """Réglages de livraison GitHub (remplis par `myop setup`)."""

    repo: str | None = None  # "owner/repo"
    pages_base: str | None = None  # "https://owner.github.io/repo/"
    private: bool = False


class Config(BaseModel):
    """Configuration complète du podcast."""

    # Identité du podcast
    title: str = "Mon Briefing"
    description: str = "L'essentiel de l'actualité, résumé chaque matin en quelques minutes."
    language: str = "fr-FR"
    author: str = "Moi"
    email: str = "moi@example.com"
    category: str = "News"  # catégorie iTunes (nom anglais : News, Technology, Society & Culture…)

    # Voix et rythme
    voice: str = "fr-FR-DeniseNeural"
    intro_rate: str = "-8%"  # débit de l'intro/outro (plus posé)
    brief_rate: str = "+4%"  # débit des brèves

    # Contenu de l'épisode
    num_headlines: int = Field(default=10, ge=1, le=30)  # titres annoncés en flash
    num_briefs: int = Field(default=4, ge=0, le=10)  # brèves détaillées
    max_brief_chars: int = Field(default=450, ge=100, le=2000)  # résumé parlé max
    max_per_source: int = Field(default=3, ge=1, le=10)  # diversité des sources

    # Comportement
    skip_if_empty: bool = True  # pas d'épisode s'il n'y a rien de nouveau
    delivery_hour: str = "07:30"  # heure de livraison (Paris)

    # Sources RSS
    sources: list[Source] = Field(default_factory=list)

    # Livraison GitHub
    github: GitHubConfig = Field(default_factory=GitHubConfig)

    @property
    def feed_url(self) -> str | None:
        base = self.github.pages_base
        if not base:
            return None
        return f"{base.rstrip('/')}/podcast.xml"


DEFAULT_SOURCES = [
    Source(name="Le Monde — À la une", url="https://www.lemonde.fr/rss/une.xml"),
    Source(name="franceinfo — Titres", url="https://www.francetvinfo.fr/titres.rss"),
    Source(name="Europe 1 — Actualités", url="https://www.europe1.fr/rss.xml"),
    Source(name="NextINpact — Numérique", url="https://www.nextinpact.com/rss"),
    Source(name="France Culture — Idées", url="https://www.radiofrance.fr/franceculture/rss"),
]


def load_config(path: Path | None = None) -> Config:
    """Charge la config ; valeurs par défaut si le fichier est absent."""
    path = path or CONFIG_PATH
    if not path.exists():
        return Config(sources=list(DEFAULT_SOURCES))
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Config.model_validate(data)


def save_config(config: Config, path: Path | None = None) -> None:
    """Écrit la config en YAML (ordre des champs préservé pour rester lisible)."""
    path = path or CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def write_default_config(path: Path | None = None) -> Config:
    """Crée config.yaml avec les valeurs par défaut (si absent)."""
    path = path or CONFIG_PATH
    if not path.exists():
        config = Config(sources=list(DEFAULT_SOURCES))
        save_config(config, path)
        return config
    return load_config(path)
