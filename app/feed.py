"""Génération du flux RSS podcast (podcast.xml), compatible iTunes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from feedgen.feed import FeedGenerator


def load_episode_metas(dist_dir: Path) -> list[dict]:
    """Charge les métadonnées des épisodes (dist/episodes/*.json), les + récents d'abord."""
    episodes_dir = dist_dir / "episodes"
    if not episodes_dir.exists():
        return []
    metas = []
    for meta_file in episodes_dir.glob("*.json"):
        try:
            metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    metas.sort(key=lambda m: m.get("id", ""), reverse=True)
    return metas


def _duration_mmss(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def build_feed(config, episodes: list[dict], base_url: str) -> str:
    """Construit le XML du flux à partir des métadonnées d'épisodes.

    `base_url` doit être l'URL publique racine (ex. https://user.github.io/repo/).
    """
    fg = FeedGenerator()
    fg.load_extension("podcast")
    base = base_url.rstrip("/") + "/"

    fg.id(base)
    fg.title(config.title)
    fg.description(config.description)
    fg.language(config.language[:2])
    fg.link(href=base, rel="alternate")
    fg.link(href=f"{base}podcast.xml", rel="self")

    fg.podcast.itunes_author(config.author)
    fg.podcast.itunes_owner(name=config.author, email=config.email)
    fg.podcast.itunes_category(config.category or "News")
    fg.podcast.itunes_image(f"{base}cover.png")
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_subtitle("Briefing quotidien généré par MYOP")

    latest = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # feedgen émet les entrées en ordre inverse d'ajout : on insère donc de la
    # plus ancienne à la plus récente pour que le flux affiche les dernières en tête.
    for meta in reversed(episodes):
        entry = fg.add_entry()
        entry.id(f"myop-{meta['id']}")  # guid stable
        entry.title(meta.get("title", meta["id"]))
        entry.description(meta.get("description", ""))
        entry.link(href=f"{base}episodes/{meta['id']}.mp3")
        pub = datetime.fromisoformat(meta["pubDate"])
        entry.pubDate(pub)
        entry.enclosure(
            url=f"{base}episodes/{meta['id']}.mp3",
            length=str(meta.get("size", 0)),
            type="audio/mpeg",
        )
        entry.podcast.itunes_duration(_duration_mmss(meta.get("duration", 0)))
        if pub > latest:
            latest = pub

    fg.updated(latest)
    return fg.rss_str(pretty=True).decode("utf-8")


def write_feed(config, dist_dir: Path) -> Path:
    """Écrit dist/podcast.xml à partir des métadonnées présentes."""
    base = config.github.pages_base
    if not base:
        raise RuntimeError(
            "URL GitHub Pages inconnue : lance `myop setup` (ou configure github.pages_base)."
        )
    episodes = load_episode_metas(dist_dir)
    xml = build_feed(config, episodes, base)
    out = dist_dir / "podcast.xml"
    out.write_text(xml, encoding="utf-8")
    return out
