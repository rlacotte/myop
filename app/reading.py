"""Liste de lecture : des articles web à faire lire dans l'épisode.

File d'attente persistée dans dist/reading.json. À la génération, les articles
présents (jusqu'à reading.max_items) sont résumés puis retirés de la file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 myop/0.1"
)
MAX_EXTRACT_CHARS = 2500  # borne envoyée à l'IA / lue en mode déterministe


@dataclass
class ReadingItem:
    url: str
    title: str
    text: str = ""  # extrait de l'article
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _reading_path(dist_dir: Path) -> Path:
    return dist_dir / "reading.json"


def load_queue(dist_dir: Path) -> list[ReadingItem]:
    path = _reading_path(dist_dir)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [ReadingItem(**item) for item in raw]
    except (json.JSONDecodeError, TypeError, OSError):
        return []


def save_queue(dist_dir: Path, queue: list[ReadingItem]) -> None:
    path = _reading_path(dist_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([item.__dict__ for item in queue], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_article(html: str, url: str = "") -> tuple[str, str]:
    """Extrait titre + texte principal d'une page (readability minimaliste).

    Stratégie : le plus gros bloc de paragraphes du <body>.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]):
        tag.decompose()

    title = (soup.title.string or "").strip() if soup.title else ""
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else url

    blocks: list[tuple[int, str]] = []
    for paragraph in soup.find_all(["p"]):
        text = re.sub(r"\s+", " ", paragraph.get_text(" ")).strip()
        if len(text) > 60:  # on écarte les chapeaux de navigation
            blocks.append((len(text), text))
    blocks.sort(reverse=True)
    body = " ".join(text for _, text in blocks[:30])[:MAX_EXTRACT_CHARS]
    return title[:200], body


async def add_article(url: str, dist_dir: Path) -> ReadingItem | None:
    """Ajoute une page web à la liste de lecture (extraction immédiate)."""
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "html" not in content_type and "xml" not in content_type:
            return None
        title, text = extract_article(resp.text, url)
    if not text:
        return None
    item = ReadingItem(url=url, title=title, text=text)
    queue = load_queue(dist_dir)
    if any(existing.url == url for existing in queue):
        return None
    queue.append(item)
    save_queue(dist_dir, queue)
    return item


def take_for_episode(dist_dir: Path, max_items: int) -> list[ReadingItem]:
    """Sort les articles à lire dans cet épisode (et les retire de la file)."""
    queue = load_queue(dist_dir)
    due, rest = queue[:max_items], queue[max_items:]
    save_queue(dist_dir, rest)
    return due
