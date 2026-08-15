"""Dashboard local MYOP : émissions, sources, épisodes, script, abonnement."""

from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import feedparser
import httpx
import qrcode
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import publish
from . import reading as reading_mod
from .config import CONFIG_PATH, Config, Show, Source, load_config, save_config
from .generate import DIST_DIR, Draft, build_draft, generate_episode
from .script import PARIS, Segment
from .tts import list_voices, voice_preview

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=BASE_DIR / "templates")

VOICE_PATTERN = re.compile(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural$")
ID_PATTERN = re.compile(r"^[a-z0-9-]{1,30}$")

# Émission ciblée par une requête : le front envoie « ?show=<id> ».
# L'alias est indispensable — sans lui FastAPI attendrait « ?show_id= » et
# toutes les requêtes retomberaient silencieusement sur la 1ʳᵉ émission.
ShowParam = Annotated[str | None, Query(alias="show")]

app = FastAPI(title="MYOP")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

(DIST_DIR / "episodes").mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=DIST_DIR / "episodes"), name="audio")

# État des jobs lancés depuis le dashboard (génération / préparation)
_jobs: dict[str, dict] = {}
# Références fortes sur les tâches de fond : sans cela la boucle asyncio n'en
# garde qu'une référence faible et le ramasse-miettes peut interrompre une
# génération en cours de route.
_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """Lance une tâche de fond en gardant une référence jusqu'à sa fin."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _job_key(show: Show) -> str:
    """Clé d'état d'une génération, toujours dérivée de l'émission résolue.

    Indispensable pour que le front (qui interroge par identifiant) retrouve
    le job, quelle que soit la façon dont la génération a été lancée.
    """
    return f"generate:{show.id}"


def _current_show(request: Request | None = None, show_id: str | None = None) -> Show:
    config = load_config()
    if show_id:
        try:
            return config.show(show_id)
        except KeyError:
            pass
    if request:
        param = request.query_params.get("show")
        if param:
            try:
                return config.show(param)
            except KeyError:
                pass
    return config.show()


# ------------------------------------------------------------------ pages ---

@app.get("/")
def page_home(request: Request):
    config = load_config()
    return TEMPLATES.TemplateResponse(
        request, "home.html", {"config": config, "show": _current_show(request)}
    )


@app.get("/reglages")
def page_settings(request: Request):
    config = load_config()
    return TEMPLATES.TemplateResponse(
        request, "settings.html", {"config": config, "show": _current_show(request)}
    )


@app.get("/sources")
def page_sources(request: Request):
    config = load_config()
    return TEMPLATES.TemplateResponse(
        request, "sources.html", {"config": config, "show": _current_show(request)}
    )


@app.get("/episodes")
def page_episodes(request: Request):
    config = load_config()
    return TEMPLATES.TemplateResponse(
        request, "episodes.html", {"config": config, "show": _current_show(request)}
    )


# ------------------------------------------------------------------ état ----

@app.get("/api/overview")
def get_overview(show_id: ShowParam = None):
    """Résumé d'une émission pour le tableau de bord (un seul aller-retour)."""
    config = load_config()
    show = _show_or_404(show_id)
    episodes = _local_episodes(show)
    draft = _draft_path(show).exists()
    running = _jobs.get(_job_key(show), {}).get("running", False)
    return {
        "show": {
            "id": show.id,
            "title": show.title,
            "enabled": show.enabled,
            "delivery_hour": show.delivery_hour,
        },
        "sources": len(show.sources),
        "episodes": len(episodes),
        "latest": episodes[0] if episodes else None,
        "has_draft": draft,
        "running": running,
        "feed_url": config.feed_url(show),
    }


@app.get("/api/state")
def get_state():
    config = load_config()
    from .ai import load_api_key

    return {
        "shows": [
            {
                "id": s.id,
                "title": s.title,
                "enabled": s.enabled,
                "delivery_hour": s.delivery_hour,
                "feed_url": config.feed_url(s),
            }
            for s in config.shows
        ],
        "current_show": _current_show().id,
        "feed_url": config.feed_url(_current_show()),
        "pages_base": config.github.pages_base,
        "repo": config.github.repo,
        "has_repo": publish.remote_slug() is not None,
        "ai_enabled": config.ai.enabled,
        "ai_model": config.ai.model,
        "ai_available": load_api_key(config) is not None,
        "voice_provider": config.audio.provider,
    }


# ------------------------------------------------------------- réglages ----

class SettingsUpdate(BaseModel):
    show_id: str | None = None
    # Champs du show
    title: str | None = None
    description: str | None = None
    voice: str | None = None
    voice_co: str | None = None
    intro_rate: str | None = None
    brief_rate: str | None = None
    num_headlines: int | None = Field(default=None, ge=1, le=30)
    num_briefs: int | None = Field(default=None, ge=0, le=10)
    max_brief_chars: int | None = Field(default=None, ge=100, le=2000)
    max_per_source: int | None = Field(default=None, ge=1, le=10)
    weather_city: str | None = None
    ephemeris: bool | None = None
    delivery_hour: str | None = None
    enabled: bool | None = None
    # Champs globaux
    author: str | None = None
    email: str | None = None
    category: str | None = None
    skip_if_empty: bool | None = None
    keep_episodes: int | None = Field(default=None, ge=0, le=1000)
    ai_enabled: bool | None = None
    ai_model: str | None = None
    ai_persona: str | None = None
    ai_system_prompt: str | None = None
    ai_tone_examples: str | None = None  # extraits séparés par une ligne « --- »
    jingle: bool | None = None
    chapters: bool | None = None


@app.put("/api/settings")
def put_settings(update: SettingsUpdate):
    config = load_config()
    show = _current_show(show_id=update.show_id)

    # Retrouve le show dans la config (objet chargé, pas une copie)
    target = next(s for s in config.shows if s.id == show.id)

    show_fields = {
        "title", "description", "voice", "voice_co", "intro_rate", "brief_rate",
        "num_headlines", "num_briefs", "max_brief_chars", "max_per_source",
        "weather_city", "ephemeris", "delivery_hour", "enabled",
    }
    global_fields = {
        "author", "email", "category", "skip_if_empty", "keep_episodes", "ai_enabled",
        "ai_model", "ai_persona", "ai_system_prompt", "ai_tone_examples", "jingle",
        "chapters",
    }
    changes = update.model_dump(exclude={"show_id"}, exclude_none=True)

    hour_pattern = re.compile(r"^(\d{2}):(\d{2})$")
    if "delivery_hour" in changes:
        match = hour_pattern.match(changes["delivery_hour"])
        valid_hour = match and int(match.group(1)) < 24 and int(match.group(2)) < 60
        if not valid_hour:
            raise HTTPException(400, "Heure invalide (format HH:MM attendu)")
    if "voice" in changes and config.audio.provider == "edge" and not VOICE_PATTERN.match(changes["voice"]):
        raise HTTPException(400, "Nom de voix invalide")
    if "voice_co" in changes and changes["voice_co"] and config.audio.provider == "edge":
        if not VOICE_PATTERN.match(changes["voice_co"]):
            raise HTTPException(400, "Nom de 2ᵉ voix invalide (vide pour désactiver le dialogue)")

    for key, value in changes.items():
        if key in show_fields:
            setattr(target, key, value)
        elif key in global_fields:
            if key == "ai_persona":
                config.ai.persona = value
            elif key == "ai_system_prompt":
                config.ai.system_prompt = value or None
            elif key == "ai_tone_examples":
                # Un bloc de texte, exemples séparés par une ligne « --- »
                config.ai.tone_examples = re.split(r"\n\s*-{3,}\s*\n", value)
            elif key == "ai_enabled":
                config.ai.enabled = value
            elif key == "ai_model":
                config.ai.model = value.strip()
            elif key == "jingle":
                config.audio.jingle = value
            elif key == "chapters":
                config.audio.chapters = value
            elif key == "keep_episodes":
                config.publishing.keep_episodes = value
            else:
                setattr(config, key, value)

    validated = Config.model_validate(config.model_dump())
    save_config(validated)
    return {"ok": True, "feed_url": validated.feed_url(target)}


class ShowCreate(BaseModel):
    title: str
    delivery_hour: str = "18:00"


@app.post("/api/shows")
def create_show(payload: ShowCreate):
    config = load_config()
    base = payload.title.strip().lower().replace(" ", "-")
    show_id = re.sub(r"[^a-z0-9-]", "", base) or "show"
    if any(s.id == show_id for s in config.shows):
        raise HTTPException(400, f"Une émission « {show_id} » existe déjà")
    config.shows.append(
        Show(
            id=show_id,
            title=payload.title.strip(),
            delivery_hour=payload.delivery_hour,
            sources=list(config.show().sources[:5]),  # départ : 5 sources du show courant
        )
    )
    save_config(config)
    return {"ok": True, "id": show_id}


@app.delete("/api/shows/{show_id}")
def delete_show(show_id: str):
    config = load_config()
    if len(config.shows) <= 1:
        raise HTTPException(400, "Impossible de supprimer la dernière émission")
    config.shows = [s for s in config.shows if s.id != show_id]
    save_config(config)
    return {"ok": True}


@app.get("/api/voices")
async def get_voices():
    return await list_voices()


@app.get("/api/voice-preview/{voice}")
async def get_voice_preview(voice: str):
    if not VOICE_PATTERN.match(voice):
        raise HTTPException(400, "Nom de voix invalide")
    path = DIST_DIR / f".preview-{voice}.mp3"
    try:
        await voice_preview(voice, path)
    except Exception as exc:
        raise HTTPException(502, f"Échec de la synthèse : {exc}") from exc
    return FileResponse(path, media_type="audio/mpeg")


# --------------------------------------------------------------- sources ----

class SourceAdd(BaseModel):
    name: str
    url: str
    show_id: str | None = None


class LibraryToggle(BaseModel):
    url: str
    enabled: bool
    show_id: str | None = None


class CategoryToggle(BaseModel):
    category: str
    enabled: bool
    show_id: str | None = None


def _show_or_404(show_id: str | None) -> Show:
    config = load_config()
    try:
        return config.show(show_id) if show_id else _current_show()
    except KeyError:
        raise HTTPException(404, "Émission inconnue")


@app.get("/api/sources")
def get_sources(show_id: ShowParam = None):
    show = _show_or_404(show_id)
    return [{"index": i, **source.model_dump()} for i, source in enumerate(show.sources)]


@app.get("/api/library")
def get_library(show_id: ShowParam = None):
    """Bibliothèque de sources intégrée, avec l'état actif pour cette émission."""
    from .library import LIBRARY

    config = load_config()
    show = _show_or_404(show_id)
    active = {source.url for source in show.sources}
    categories = [
        {
            "category": category,
            "feeds": [{**feed, "active": feed["url"] in active} for feed in feeds],
        }
        for category, feeds in LIBRARY.items()
    ]
    custom = [
        {"index": i, "name": source.name, "url": source.url}
        for i, source in enumerate(show.sources)
        if source.url not in _library_urls()
    ]
    return {
        "categories": categories,
        "custom": custom,
        "active_count": len(show.sources),
    }


def _library_urls() -> set[str]:
    from .library import library_urls

    return library_urls()


def _find_in_library(url: str) -> dict | None:
    from .library import LIBRARY

    for feeds in LIBRARY.values():
        for feed in feeds:
            if feed["url"] == url:
                return feed
    return None


@app.post("/api/library/toggle")
def toggle_library_source(payload: LibraryToggle):
    """Active ou désactive un flux de la bibliothèque pour cette émission."""
    feed = _find_in_library(payload.url)
    if not feed:
        raise HTTPException(404, "Flux inconnu dans la bibliothèque")
    config = load_config()
    show = _show_or_404(payload.show_id)
    target = next(s for s in config.shows if s.id == show.id)
    urls = {source.url for source in target.sources}
    if payload.enabled and feed["url"] not in urls:
        target.sources.append(Source(name=feed["name"], url=feed["url"]))
    elif not payload.enabled and feed["url"] in urls:
        target.sources = [s for s in target.sources if s.url != feed["url"]]
    else:
        return {"ok": True, "unchanged": True}
    save_config(config)
    return {"ok": True, "active_count": len(target.sources)}


@app.post("/api/library/category")
def toggle_library_category(payload: CategoryToggle):
    """Active ou désactive toute une catégorie pour cette émission."""
    from .library import LIBRARY

    feeds = LIBRARY.get(payload.category)
    if feeds is None:
        raise HTTPException(404, "Catégorie inconnue")
    config = load_config()
    show = _show_or_404(payload.show_id)
    target = next(s for s in config.shows if s.id == show.id)
    category_urls = {feed["url"] for feed in feeds}
    if payload.enabled:
        existing = {source.url for source in target.sources}
        for feed in feeds:
            if feed["url"] not in existing:
                target.sources.append(Source(name=feed["name"], url=feed["url"]))
    else:
        target.sources = [s for s in target.sources if s.url not in category_urls]
    save_config(config)
    return {"ok": True, "active_count": len(target.sources)}


@app.post("/api/sources")
def add_source(payload: SourceAdd):
    name, url = payload.name.strip(), payload.url.strip()
    if not name or not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Nom requis et URL doit commencer par http(s)://")
    config = load_config()
    show = _show_or_404(payload.show_id)
    target = next(s for s in config.shows if s.id == show.id)
    if any(source.url == url for source in target.sources):
        raise HTTPException(400, "Ce flux est déjà dans tes sources")
    target.sources.append(Source(name=name, url=url))
    save_config(config)
    return {"ok": True}


@app.delete("/api/sources/{index}")
def delete_source(index: int, show_id: ShowParam = None):
    config = load_config()
    show = _show_or_404(show_id)
    target = next(s for s in config.shows if s.id == show.id)
    if not 0 <= index < len(target.sources):
        raise HTTPException(404, "Source inconnue")
    target.sources.pop(index)
    save_config(config)
    return {"ok": True}


@app.get("/api/sources/preview")
async def preview_source(url: str):
    """Récupère les 5 derniers items d'un flux (bouton « Tester »)."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL invalide")

    from .sources import USER_AGENT, entry_date
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(502, f"Flux inaccessible : {exc.__class__.__name__}") from exc

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise HTTPException(422, "Ce lien ne semble pas être un flux RSS valide")
    items = []
    for entry in parsed.entries[:5]:
        date = entry_date(entry)
        items.append(
            {
                "title": (entry.get("title") or "").strip()[:140],
                "date": date.strftime("%d/%m %Hh%M") if date else "—",
                "url": entry.get("link", ""),
            }
        )
    return {"feed_title": parsed.feed.get("title", ""), "items": items}


@app.get("/api/sources/health")
async def sources_health(show_id: ShowParam = None):
    """Santé de toutes les sources actives (test parallèle en direct)."""
    show = _show_or_404(show_id)

    async def one(source) -> dict:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 myop/0.1"},
                timeout=12,
                follow_redirects=True,
            ) as client:
                started = asyncio.get_event_loop().time()
                resp = await client.get(source.url)
                elapsed = int((asyncio.get_event_loop().time() - started) * 1000)
                resp.raise_for_status()
                entries = feedparser.parse(resp.content).entries
                dates = [entry_date(e) for e in entries if entry_date(e)]
                latest = max(dates).strftime("%d/%m %Hh%M") if dates else "—"
                return {
                    "name": source.name, "ok": True, "items": len(entries),
                    "latest": latest, "ms": elapsed,
                }
        except Exception as exc:
            return {"name": source.name, "ok": False, "error": exc.__class__.__name__}

    from .sources import entry_date

    results = await asyncio.gather(*[one(source) for source in show.sources])
    return list(results)


# ------------------------------------------------------------------ OPML ----

@app.get("/api/opml")
def export_opml(show_id: ShowParam = None):
    """Export OPML des sources actives (interopérable avec les lecteurs RSS)."""
    show = _show_or_404(show_id)
    outlines = "\n".join(
        f'    <outline type="rss" text="{source.name}" title="{source.name}" '
        f'xmlUrl="{source.url}"/>' for source in show.sources
    )
    opml = f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>MYOP — sources de « {show.title} »</title></head>
  <body>
{outlines}
  </body>
</opml>"""
    return Response(
        content=opml, media_type="text/x-opml",
        headers={"Content-Disposition": f"attachment; filename=myop-{show.id}.opml"},
    )


class OpmlImport(BaseModel):
    content: str
    show_id: str | None = None


@app.post("/api/opml")
def import_opml(payload: OpmlImport):
    """Importe des flux depuis un fichier OPML (xmlUrl des outline)."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(payload.content)
    except ET.ParseError:
        raise HTTPException(422, "OPML invalide")
    urls = []
    for outline in root.iter("outline"):
        url = (outline.get("xmlUrl") or outline.get("xmlurl") or "").strip()
        name = (outline.get("title") or outline.get("text") or url).strip()
        if url.startswith(("http://", "https://")):
            urls.append((name, url))
    if not urls:
        raise HTTPException(422, "Aucun flux trouvé dans cet OPML")

    config = load_config()
    show = _show_or_404(payload.show_id)
    target = next(s for s in config.shows if s.id == show.id)
    existing = {source.url for source in target.sources}
    added = 0
    for name, url in urls:
        if url not in existing:
            target.sources.append(Source(name=name[:80] or url, url=url))
            added += 1
    save_config(config)
    return {"ok": True, "added": added, "total": len(target.sources)}


# --------------------------------------------------------- liste de lecture --

class ReadingAdd(BaseModel):
    url: str


@app.get("/api/reading")
def get_reading():
    queue = reading_mod.load_queue(DIST_DIR)
    return [
        {"url": item.url, "title": item.title, "chars": len(item.text)}
        for item in queue
    ]


@app.post("/api/reading")
async def add_reading(payload: ReadingAdd):
    if not payload.url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL invalide")
    try:
        item = await reading_mod.add_article(payload.url.strip(), DIST_DIR)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Page inaccessible : {exc.__class__.__name__}") from exc
    if item is None:
        raise HTTPException(422, "Rien à lire sur cette page (ou déjà dans la liste)")
    return {"ok": True, "title": item.title}


@app.delete("/api/reading/{index}")
def delete_reading(index: int):
    queue = reading_mod.load_queue(DIST_DIR)
    if not 0 <= index < len(queue):
        raise HTTPException(404, "Article inconnu")
    queue.pop(index)
    reading_mod.save_queue(DIST_DIR, queue)
    return {"ok": True}


# ------------------------------------------------------------- épisodes -----

def _local_episodes(show: Show) -> list[dict]:
    metas = []
    episodes_dir = DIST_DIR / "episodes" / show.id
    if not episodes_dir.exists() and show.id == "matin":
        episodes_dir = DIST_DIR / "episodes"
    if not episodes_dir.exists():
        return []
    for meta_file in episodes_dir.glob("*.json"):
        try:
            metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    metas.sort(key=lambda m: m.get("id", ""), reverse=True)
    for meta in metas:
        meta["local"] = (episodes_dir / f"{meta['id']}.mp3").exists()
        meta["audio"] = f"/audio/{show.id}/{meta['id']}.mp3"
    return metas


@app.get("/api/episodes")
def get_episodes(show_id: ShowParam = None):
    return _local_episodes(_show_or_404(show_id))


@app.post("/api/sync-remote")
async def sync_remote():
    """Récupère les métadonnées d'épisodes déjà publiées sur gh-pages."""
    try:
        await asyncio.to_thread(publish.fetch_existing, DIST_DIR)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    config = load_config()
    return {show.id: _local_episodes(show) for show in config.shows if show.enabled}


class GenerateRequest(BaseModel):
    show_id: str | None = None
    date: str | None = None  # rattrapage AAAA-MM-JJ
    fresh: bool = False


@app.post("/api/generate")
async def start_generation(payload: GenerateRequest | None = None):
    payload = payload or GenerateRequest()
    config = load_config()
    try:
        show = config.show(payload.show_id)
    except KeyError:
        raise HTTPException(404, "Émission inconnue")

    job_key = _job_key(show)
    if _jobs.get(job_key, {}).get("running"):
        raise HTTPException(409, "Une génération est déjà en cours pour cette émission")

    now = None
    if payload.date:
        try:
            day = datetime.strptime(payload.date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "Date invalide (AAAA-MM-JJ)")
        now = datetime.now(tz=PARIS).replace(
            year=day.year, month=day.month, day=day.day
        )

    _jobs[job_key] = {"running": True, "log": [], "result": None}
    job = _jobs[job_key]

    async def _run():
        job["log"].append("Récupération de l'historique…")
        try:
            await asyncio.to_thread(publish.fetch_existing, DIST_DIR)
            job["log"].append("Collecte des flux, météo, liste de lecture… puis synthèse vocale")
            result = await generate_episode(
                load_config(), show, now=now, ignore_seen=payload.fresh
            )
            job["result"] = {
                "ok": result.ok,
                "reason": result.reason,
                "show_id": result.show_id,
                "episode_id": result.episode_id,
                "duration": result.duration,
                "size": result.size,
                "titles": result.titles,
                "warnings": result.warnings,
                "ai_used": result.ai_used,
                "chapters": result.chapter_titles,
                "reading_count": result.reading_count,
            }
            job["log"].append("Terminé ✅" if result.ok else f"Aucun épisode : {result.reason}")
        except Exception as exc:  # le dashboard ne doit jamais crasher
            job["result"] = {"ok": False, "reason": f"{exc.__class__.__name__} : {exc}"}
            job["log"].append(f"Erreur : {exc}")
        finally:
            job["running"] = False

    _spawn(_run())
    return {"ok": True}


@app.get("/api/generate/status")
def generation_status(show_id: ShowParam = None):
    job = _jobs.get(_job_key(_show_or_404(show_id)), {})
    return {"running": job.get("running", False), "log": job.get("log", []), "result": job.get("result")}


# ------------------------------------------------------- éditeur de script ---

class RenderRequest(BaseModel):
    show_id: str | None = None
    segments: list[dict]  # [{kind, text, speaker?}]
    items_keys: list[str] = []
    titles: list[str] = []
    title: str | None = None  # titre retouché (défaut : celui de l'émission)
    description: str = ""
    ai_used: bool = False
    reading_items: list[dict] = []


def _draft_path(show: Show) -> Path:
    return DIST_DIR / f"draft-{show.id}.json"


def _draft_payload(draft: Draft) -> dict:
    return {
        "show_id": draft.show_id,
        "episode_id": draft.episode_id,
        "title": draft.title,
        "description": draft.description,
        "segments": [segment.__dict__ for segment in draft.segments],
        "titles": draft.titles,
        "ai_used": draft.ai_used,
        "warnings": draft.warnings,
        "items_keys": draft.items_keys,
        # Sans eux, les articles lus ne quittaient pas la file d'attente
        "reading_items": [item.__dict__ for item in draft.reading_items],
    }


def _save_draft(show: Show, payload: dict) -> None:
    path = _draft_path(show)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@app.post("/api/script/draft")
async def script_draft(show_id: ShowParam = None):
    """Prépare le script (collecte + IA/déterministe) sans le synthétiser."""
    config = load_config()
    try:
        show = config.show(show_id)
    except KeyError:
        raise HTTPException(404, "Émission inconnue")
    try:
        await asyncio.to_thread(publish.fetch_existing, DIST_DIR)
        draft = await build_draft(config, show)
    except Exception as exc:
        raise HTTPException(502, f"{exc.__class__.__name__} : {exc}") from exc
    payload = _draft_payload(draft)
    _save_draft(show, payload)  # rechargeable après un aller-retour dans le navigateur
    return payload


@app.get("/api/script/draft")
def get_script_draft(show_id: ShowParam = None):
    """Brouillon en cours, pour reprendre l'édition après un rechargement."""
    show = _show_or_404(show_id)
    path = _draft_path(show)
    if not path.exists():
        return {"draft": None}
    try:
        return {"draft": json.loads(path.read_text(encoding="utf-8"))}
    except (json.JSONDecodeError, OSError):
        return {"draft": None}


class DraftSave(BaseModel):
    show_id: str | None = None
    segments: list[dict]
    title: str | None = None
    description: str | None = None


@app.put("/api/script/draft")
def save_script_draft(payload: DraftSave):
    """Enregistre les retouches en cours (le travail survit à un rechargement)."""
    show = _show_or_404(payload.show_id)
    path = _draft_path(show)
    stored = {}
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}
    stored["segments"] = payload.segments
    if payload.title is not None:
        stored["title"] = payload.title
    if payload.description is not None:
        stored["description"] = payload.description
    _save_draft(show, stored)
    return {"ok": True, "segments": len(payload.segments)}


@app.delete("/api/script/draft")
def delete_script_draft(show_id: ShowParam = None):
    _draft_path(_show_or_404(show_id)).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/script/render")
async def script_render(payload: RenderRequest):
    """Synthétise l'épisode à partir du script (éventuellement édité)."""
    config = load_config()
    try:
        show = config.show(payload.show_id)
    except KeyError:
        raise HTTPException(404, "Émission inconnue")
    if not payload.segments:
        raise HTTPException(400, "Script vide")

    segments = [
        Segment(
            kind=s.get("kind", "brief"),
            text=(s.get("text") or "").strip(),
            rate=s.get("rate") or show.brief_rate,
            speaker=s.get("speaker") if s.get("speaker") in ("host", "co") else None,
        )
        for s in payload.segments
        if (s.get("text") or "").strip()
    ]
    if not segments:
        raise HTTPException(400, "Script vide après nettoyage")

    reading_items = [reading_mod.ReadingItem(**item) for item in payload.reading_items]

    from .script import episode_title

    now = datetime.now(tz=PARIS)
    draft = Draft(
        show_id=show.id,
        episode_id=now.date().isoformat(),
        # Le titre suit l'émission choisie (pas un « Briefing » en dur)
        title=(payload.title or "").strip() or episode_title(show, now),
        description=payload.description or " • ".join(payload.titles[:5]),
        segments=segments,
        titles=payload.titles,
        ai_used=payload.ai_used,
        items_keys=payload.items_keys,
        reading_items=reading_items,
    )

    job_key = _job_key(show)
    if _jobs.get(job_key, {}).get("running"):
        raise HTTPException(409, "Une génération est déjà en cours pour cette émission")
    _jobs[job_key] = {"running": True, "log": ["Synthèse du script édité…"], "result": None}
    job = _jobs[job_key]

    async def _run():
        try:
            result = await generate_episode(config, show, draft=draft)
            job["result"] = {
                "ok": result.ok, "reason": result.reason, "show_id": result.show_id,
                "episode_id": result.episode_id, "duration": result.duration,
                "size": result.size, "titles": result.titles, "warnings": result.warnings,
                "ai_used": result.ai_used, "chapters": result.chapter_titles,
                "reading_count": result.reading_count,
            }
            if result.ok:  # brouillon consommé — conservé en cas d'échec
                _draft_path(show).unlink(missing_ok=True)
            job["log"].append("Terminé ✅")
        except Exception as exc:
            job["result"] = {"ok": False, "reason": f"{exc.__class__.__name__} : {exc}"}
            job["log"].append(f"Erreur : {exc}")
        finally:
            job["running"] = False

    _spawn(_run())
    return {"ok": True}


# -------------------------------------------------------------- feedback ----

class FeedbackVote(BaseModel):
    source: str
    title: str
    good: bool


@app.post("/api/feedback")
def vote(payload: FeedbackVote):
    from .feedback import record_vote

    feedback = record_vote(DIST_DIR, source=payload.source, title=payload.title, good=payload.good)
    return {
        "ok": True,
        "source_score": feedback.source_scores.get(payload.source, 0),
        "disliked_keywords": feedback.disliked_keywords[-10:],
    }


@app.get("/api/feedback")
def get_feedback():
    from .feedback import load_feedback

    feedback = load_feedback(DIST_DIR)
    return {
        "source_scores": feedback.source_scores,
        "disliked_keywords": feedback.disliked_keywords,
    }


@app.delete("/api/feedback")
def reset_feedback():
    from .feedback import Feedback, save_feedback

    save_feedback(DIST_DIR, Feedback())
    return {"ok": True}


# ------------------------------------------------------------- publication --

async def _git_step(func, *args):
    """Exécute une étape git/gh sans bloquer la boucle événementielle."""
    try:
        await asyncio.to_thread(func, *args)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/publish-config")
async def publish_config():
    await _git_step(publish.push_config, CONFIG_PATH)
    return {"ok": True, "message": "Config poussée sur GitHub ✓"}


@app.post("/api/publish-dist")
async def publish_dist_endpoint():
    if not any((DIST_DIR / "episodes").glob("**/*.json")):
        raise HTTPException(400, "Aucun épisode à publier — génère-en un d'abord")
    await _git_step(publish.publish_dist, DIST_DIR, "publication depuis le dashboard")
    return {"ok": True, "message": "Épisodes publiés sur GitHub Pages ✓"}


@app.post("/api/trigger")
async def trigger_workflow():
    await _git_step(publish.trigger_workflow)
    return {"ok": True, "message": "Workflow GitHub Actions déclenché 🚀"}


@app.get("/api/qr.png")
def feed_qr_png(show_id: ShowParam = None):
    """QR code du flux RSS : à scanner depuis le lecteur de podcast du téléphone."""
    config = load_config()
    show = _show_or_404(show_id)
    feed_url = config.feed_url(show)
    if not feed_url:
        raise HTTPException(404, "Flux pas encore configuré (lance `myop setup`)")
    img = qrcode.make(feed_url, box_size=8, border=2)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")
