"""Mode distant : faire tourner le dashboard sur une plateforme sans disque.

Sur Vercel, le système de fichiers est en lecture seule (hors /tmp, éphémère)
et rien ne survit à une requête. Plutôt que d'ajouter une base de données,
MYOP réutilise ce qui fait déjà autorité : **le dépôt GitHub**.

- lecture : les fichiers publics sont lus en HTTP (raw.githubusercontent), sans
  jeton et sans quota d'API ;
- écriture : l'API Contents commite le fichier, donc le prochain passage de
  GitHub Actions travaille avec les réglages à jour ;
- le cache local vit dans /tmp, simple accélérateur reconstruit à froid.

Ce que le mode distant ne fait pas : produire un épisode. La synthèse vocale
réclame ffmpeg et plusieurs minutes — cela reste le travail du workflow.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
TIMEOUT = 15


def is_remote() -> bool:
    """Vrai quand le dashboard tourne sur une plateforme sans disque."""
    return bool(os.environ.get("VERCEL") or os.environ.get("MYOP_REMOTE"))


def repo_slug() -> str | None:
    return os.environ.get("MYOP_REPO") or None


def token() -> str | None:
    return os.environ.get("MYOP_GITHUB_TOKEN") or None


def can_write() -> bool:
    """Écrire suppose un dépôt ET un jeton : sinon le dashboard est en lecture."""
    return bool(repo_slug() and token())


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "myop"}
    if token():
        headers["Authorization"] = f"Bearer {token()}"
    return headers


def read_file(path: str, branch: str = "main") -> str | None:
    """Contenu d'un fichier du dépôt (via raw, puis l'API si le dépôt est privé)."""
    slug = repo_slug()
    if not slug:
        return None
    try:
        response = httpx.get(f"{RAW}/{slug}/{branch}/{path}", timeout=TIMEOUT)
        if response.status_code == 200:
            return response.text
    except httpx.HTTPError:
        pass
    if not token():
        return None
    try:
        response = httpx.get(
            f"{API}/repos/{slug}/contents/{path}",
            params={"ref": branch},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            return None
        return base64.b64decode(response.json()["content"]).decode("utf-8")
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def _sha(path: str, branch: str) -> str | None:
    """SHA du fichier existant — exigé par l'API pour un remplacement."""
    try:
        response = httpx.get(
            f"{API}/repos/{repo_slug()}/contents/{path}",
            params={"ref": branch},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        return response.json().get("sha") if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def write_file(path: str, content: str, message: str, branch: str = "main") -> bool:
    """Commite un fichier dans le dépôt. Faux si l'écriture est impossible."""
    if not can_write():
        return False
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": branch,
        "committer": {"name": "myop-dashboard", "email": "myop-bot@users.noreply.github.com"},
    }
    sha = _sha(path, branch)
    if sha:
        payload["sha"] = sha
    try:
        response = httpx.put(
            f"{API}/repos/{repo_slug()}/contents/{path}",
            json=payload,
            headers=_headers(),
            timeout=TIMEOUT,
        )
        return response.status_code in (200, 201)
    except httpx.HTTPError:
        return False


def dispatch_workflow(workflow: str = "daily.yml", inputs: dict | None = None) -> bool:
    """Déclenche le workflow de génération (l'épisode se fabrique là-bas)."""
    if not can_write():
        return False
    try:
        response = httpx.post(
            f"{API}/repos/{repo_slug()}/actions/workflows/{workflow}/dispatches",
            json={"ref": "main", "inputs": inputs or {}},
            headers=_headers(),
            timeout=TIMEOUT,
        )
        return response.status_code == 204
    except httpx.HTTPError:
        return False


# ------------------------------------------------------------------ config ---

CACHE_DIR = Path("/tmp/myop")
CONFIG_CACHE = CACHE_DIR / "config.yaml"


def hydrate_config() -> Path | None:
    """Récupère config.yaml du dépôt dans le cache local. Retourne son chemin."""
    content = read_file("config.yaml")
    if content is None:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_CACHE.write_text(content, encoding="utf-8")
    return CONFIG_CACHE


def push_config(path: Path) -> bool:
    """Renvoie la config éditée vers le dépôt (le workflow la lira ensuite)."""
    return write_file(
        "config.yaml", path.read_text(encoding="utf-8"), "réglages : mise à jour depuis le dashboard"
    )


def push_state(name: str, content: str) -> bool:
    """État partagé avec le générateur (file de lecture, votes) sur gh-pages.

    C'est là que `fetch_existing` va les chercher au début de chaque
    génération : écrire ailleurs serait sans effet.
    """
    return write_file(name, content, f"dashboard : {name}", branch="gh-pages")


def episodes_from_feed(feed_url: str) -> list[dict]:
    """Liste des épisodes lue dans le flux public — aucun disque nécessaire."""
    import feedparser

    try:
        response = httpx.get(feed_url, timeout=TIMEOUT, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    parsed = feedparser.parse(response.content)
    episodes = []
    for entry in parsed.entries:
        enclosure = next(iter(entry.get("enclosures", []) or []), {})
        url = enclosure.get("href", "")
        episodes.append(
            {
                "id": url.rsplit("/", 1)[-1].removesuffix(".mp3") or entry.get("id", ""),
                "title": entry.get("title", ""),
                "description": entry.get("summary", ""),
                "pubDate": entry.get("published", ""),
                "duration": _seconds(entry.get("itunes_duration", "")),
                "size": int(enclosure.get("length") or 0),
                "local": bool(url),
                "audio": url,
            }
        )
    return episodes


def _seconds(duration: str) -> int:
    """« 6:12 » ou « 372 » → secondes."""
    parts = str(duration).split(":")
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return 0
    total = 0
    for number in numbers:
        total = total * 60 + number
    return total
