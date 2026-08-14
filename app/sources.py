"""Collecte des articles depuis les flux RSS configurés.

Fetch parallèle, filtrage par fenêtre de temps, dédoublonnage
inter-sources et historisation via seen.json.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from time import mktime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from .config import Config, Source

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 myop/0.1"
)

# Paramètres de tracking à ignorer pour comparer deux URL d'article
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "ref", "source")


@dataclass
class FeedItem:
    """Un article candidat pour l'épisode."""

    title: str
    url: str
    published: datetime | None  # UTC
    summary: str  # texte nettoyé
    source_name: str
    guid: str

    @property
    def key(self) -> str:
        """Identifiant stable de dédoublonnage.

        L'URL normalisée prime sur le guid : un même article syndiqué sur
        plusieurs flux garde la même URL mais change de guid.
        """
        return normalize_url(self.url) or self.guid


@dataclass
class FetchResult:
    """Résultat de la collecte."""

    selected: list[FeedItem] = field(default_factory=list)  # items retenus pour l'épisode
    all_keys: list[str] = field(default_factory=list)  # toutes les clés vues (maj seen.json)
    errors: list[str] = field(default_factory=list)  # sources en échec


def normalize_url(url: str) -> str:
    """Normalise une URL : retire les paramètres de tracking, fragments, slash final."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def clean_html(html: str, max_chars: int | None = None) -> str:
    """Convertit un résumé HTML en texte parlé propre."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ")
    text = re.sub(r"https?://\S+", "", text)  # les URL brutes ne se lisent pas à voix haute
    text = re.sub(r"\s+", " ", text).replace("\xa0", " ").strip()
    text = re.sub(r"\s+([,;:.!?…])", r"\1", text)
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    if max_chars and len(text) > max_chars:
        cut = text[:max_chars]
        # Coupure propre : fin de phrase, sinon dernier mot + points de suspension
        for punct in (". ", "! ", "? "):
            idx = cut.rfind(punct)
            if idx > 0:
                return cut[: idx + 1].strip()
        if not cut.endswith("."):
            cut = cut.rsplit(" ", 1)[0] + "…"
    return text.strip()


def entry_date(entry) -> datetime | None:
    """Date de publication d'une entrée feedparser, en UTC."""
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct:
        return None
    try:
        return datetime.fromtimestamp(mktime(struct), tz=timezone.utc)
    except (OverflowError, ValueError):
        return None


def _to_item(entry, source: Source) -> FeedItem | None:
    title = clean_html(entry.get("title") or "")
    link = (entry.get("link") or "").strip()
    if not title or not link:
        return None
    raw_summary = entry.get("summary") or entry.get("description") or ""
    return FeedItem(
        title=title,
        url=link,
        published=entry_date(entry),
        summary=clean_html(raw_summary),
        source_name=source.name,
        guid=(entry.get("id") or "").strip(),
    )


async def _fetch_one(
    client: httpx.AsyncClient, source: Source
) -> tuple[Source, list, str | None]:
    try:
        resp = await client.get(source.url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        return source, parsed.entries[:30], None
    except Exception as exc:  # réseau, HTTP, parse… on ignore la source en échec
        return source, [], f"{source.name} : {exc.__class__.__name__}"


def _filter_window(items: list[FeedItem], now: datetime, window: timedelta) -> list[FeedItem]:
    """Garde les items publiés dans la fenêtre (avec une petite tolérance horloge)."""
    fresh: list[FeedItem] = []
    for item in items:
        if item.published is None:  # sans date on garde : seen.json évitera les répétitions
            fresh.append(item)
        elif now - window <= item.published <= now + timedelta(hours=2):
            fresh.append(item)
    return fresh


def _select(items: list[FeedItem], config: Config) -> list[FeedItem]:
    """Trie par fraîcheur puis sélectionne en respectant max_per_source."""
    # Les plus récents d'abord ; les items sans date passent en dernier.
    ordered = sorted(
        items,
        key=lambda i: (i.published is not None, i.published or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )
    selected: list[FeedItem] = []
    per_source: dict[str, int] = {}
    wanted = config.num_headlines
    for item in ordered:
        if len(selected) >= wanted:
            break
        count = per_source.get(item.source_name, 0)
        if count >= config.max_per_source:
            continue
        per_source[item.source_name] = count + 1
        selected.append(item)
    return selected


async def fetch_items(
    config: Config,
    *,
    now: datetime | None = None,
    seen: set[str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    """Collecte tous les flux, filtre, dédoublonne et sélectionne les items.

    - fenêtre de 24 h, élargie à 48 h si trop peu d'items
    - les clés déjà présentes dans `seen` sont ignorées
    """
    now = now or datetime.now(timezone.utc)
    seen = seen or set()
    result = FetchResult()
    if not config.sources:
        return result

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
        )
    try:
        fetched = await asyncio.gather(
            *[_fetch_one(client, source) for source in config.sources]
        )
    finally:
        if own_client:
            await client.aclose()

    all_items: list[FeedItem] = []
    for source, entries, error in fetched:
        if error:
            result.errors.append(error)
        for entry in entries:
            item = _to_item(entry, source)
            if item:
                all_items.append(item)

    # Dédoublonnage inter-sources (même article syndiqué) + historique
    by_key: dict[str, FeedItem] = {}
    for item in all_items:
        result.all_keys.append(item.key)
        if item.key not in seen:
            by_key.setdefault(item.key, item)

    items = list(by_key.values())
    for window in (timedelta(hours=24), timedelta(hours=48)):
        fresh = _filter_window(items, now, window)
        if len(fresh) >= 3 or window == timedelta(hours=48):
            break

    result.selected = _select(fresh, config)
    return result
