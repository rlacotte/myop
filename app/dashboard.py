"""Dashboard local MYOP : réglages, sources, épisodes, abonnement."""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path

import qrcode
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import publish
from .config import CONFIG_PATH, Config, Source, load_config, save_config
from .generate import DIST_DIR, generate_episode
from .tts import list_voices, voice_preview

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=BASE_DIR / "templates")

VOICE_PATTERN = re.compile(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural$")
HOUR_PATTERN = re.compile(r"^\d{2}:\d{2}$")

app = FastAPI(title="MYOP")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Servir les MP3 générés localement pour l'écoute dans le dashboard
(DIST_DIR / "episodes").mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=DIST_DIR / "episodes"), name="audio")

# État du job de génération lancé depuis le dashboard
_job: dict = {"running": False, "log": [], "result": None}


# ------------------------------------------------------------------ pages ---

@app.get("/")
def page_settings(request: Request):
    return TEMPLATES.TemplateResponse(request, "settings.html", {"config": load_config()})


@app.get("/sources")
def page_sources(request: Request):
    return TEMPLATES.TemplateResponse(request, "sources.html", {"config": load_config()})


@app.get("/episodes")
def page_episodes(request: Request):
    return TEMPLATES.TemplateResponse(request, "episodes.html", {"config": load_config()})


# ------------------------------------------------------------------ état ----

@app.get("/api/state")
def get_state():
    config = load_config()
    from .ai import load_api_key

    return {
        "title": config.title,
        "feed_url": config.feed_url,
        "pages_base": config.github.pages_base,
        "repo": config.github.repo,
        "has_repo": publish.remote_slug() is not None,
        "delivery_hour": config.delivery_hour,
        "ai_enabled": config.ai.enabled,
        "ai_model": config.ai.model,
        "ai_available": load_api_key(config) is not None,
    }


# ------------------------------------------------------------- réglages ----

class SettingsUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    author: str | None = None
    email: str | None = None
    category: str | None = None
    voice: str | None = None
    intro_rate: str | None = None
    brief_rate: str | None = None
    num_headlines: int | None = Field(default=None, ge=1, le=30)
    num_briefs: int | None = Field(default=None, ge=0, le=10)
    max_brief_chars: int | None = Field(default=None, ge=100, le=2000)
    max_per_source: int | None = Field(default=None, ge=1, le=10)
    skip_if_empty: bool | None = None
    delivery_hour: str | None = None
    ai_enabled: bool | None = None
    ai_model: str | None = None


@app.put("/api/settings")
def put_settings(update: SettingsUpdate):
    config = load_config()
    changes = update.model_dump(exclude_none=True)

    if "delivery_hour" in changes:
        if not HOUR_PATTERN.match(changes["delivery_hour"]):
            raise HTTPException(400, "Heure invalide (format HH:MM attendu)")
        if config.delivery_hour != changes["delivery_hour"]:
            publish.update_workflow_cron(changes["delivery_hour"])

    # Section IA : mapping vers l'objet imbriqué
    if "ai_enabled" in changes:
        config.ai.enabled = changes.pop("ai_enabled")
    if "ai_model" in changes:
        config.ai.model = changes.pop("ai_model").strip()

    validated = Config.model_validate(config.model_copy(update=changes).model_dump())
    save_config(validated)
    return {"ok": True, "feed_url": validated.feed_url}


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


class SourceMove(BaseModel):
    direction: int  # -1 = monter, +1 = descendre


class LibraryToggle(BaseModel):
    url: str
    enabled: bool


class CategoryToggle(BaseModel):
    category: str
    enabled: bool


@app.get("/api/sources")
def get_sources():
    config = load_config()
    return [{"index": i, **source.model_dump()} for i, source in enumerate(config.sources)]


@app.get("/api/library")
def get_library():
    """Bibliothèque de sources intégrée, avec l'état actif de chaque flux."""
    from .library import LIBRARY

    config = load_config()
    active = {source.url for source in config.sources}
    categories = [
        {
            "category": category,
            "feeds": [{**feed, "active": feed["url"] in active} for feed in feeds],
        }
        for category, feeds in LIBRARY.items()
    ]
    custom = [
        {"index": i, "name": source.name, "url": source.url}
        for i, source in enumerate(config.sources)
        if source.url not in _library_urls()
    ]
    return {
        "categories": categories,
        "custom": custom,
        "active_count": len(config.sources),
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
    """Active ou désactive un flux de la bibliothèque."""
    feed = _find_in_library(payload.url)
    if not feed:
        raise HTTPException(404, "Flux inconnu dans la bibliothèque")
    config = load_config()
    urls = {source.url for source in config.sources}
    if payload.enabled and feed["url"] not in urls:
        config.sources.append(Source(name=feed["name"], url=feed["url"]))
    elif not payload.enabled and feed["url"] in urls:
        config.sources = [s for s in config.sources if s.url != feed["url"]]
    else:
        return {"ok": True, "unchanged": True}
    save_config(config)
    return {"ok": True, "active_count": len(config.sources)}


@app.post("/api/library/category")
def toggle_library_category(payload: CategoryToggle):
    """Active ou désactive toute une catégorie de la bibliothèque."""
    from .library import LIBRARY

    feeds = LIBRARY.get(payload.category)
    if feeds is None:
        raise HTTPException(404, "Catégorie inconnue")
    config = load_config()
    category_urls = {feed["url"] for feed in feeds}
    if payload.enabled:
        existing = {source.url for source in config.sources}
        for feed in feeds:
            if feed["url"] not in existing:
                config.sources.append(Source(name=feed["name"], url=feed["url"]))
    else:
        config.sources = [s for s in config.sources if s.url not in category_urls]
    save_config(config)
    return {"ok": True, "active_count": len(config.sources)}


@app.post("/api/sources")
def add_source(payload: SourceAdd):
    name, url = payload.name.strip(), payload.url.strip()
    if not name or not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Nom requis et URL doit commencer par http(s)://")
    config = load_config()
    if any(source.url == url for source in config.sources):
        raise HTTPException(400, "Ce flux est déjà dans tes sources")
    config.sources.append(Source(name=name, url=url))
    save_config(config)
    return {"ok": True}


@app.delete("/api/sources/{index}")
def delete_source(index: int):
    config = load_config()
    if not 0 <= index < len(config.sources):
        raise HTTPException(404, "Source inconnue")
    config.sources.pop(index)
    save_config(config)
    return {"ok": True}


@app.post("/api/sources/{index}/move")
def move_source(index: int, payload: SourceMove):
    config = load_config()
    new_index = index + payload.direction
    if not 0 <= index < len(config.sources) or not 0 <= new_index < len(config.sources):
        raise HTTPException(400, "Déplacement impossible")
    config.sources[index], config.sources[new_index] = (
        config.sources[new_index],
        config.sources[index],
    )
    save_config(config)
    return {"ok": True}


@app.get("/api/sources/preview")
async def preview_source(url: str):
    """Récupère les 5 derniers items d'un flux (bouton « Tester »)."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL invalide")

    import feedparser
    import httpx

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


# --------------------------------------------------------------- épisodes ---

def _local_episodes() -> list[dict]:
    metas = []
    for meta_file in (DIST_DIR / "episodes").glob("*.json"):
        try:
            metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    metas.sort(key=lambda meta: meta.get("id", ""), reverse=True)
    for meta in metas:
        meta["local"] = (DIST_DIR / "episodes" / f"{meta['id']}.mp3").exists()
    return metas


@app.get("/api/episodes")
def get_episodes():
    return _local_episodes()


@app.post("/api/sync-remote")
async def sync_remote():
    """Récupère les métadonnées d'épisodes déjà publiées sur gh-pages."""
    try:
        await asyncio.to_thread(publish.fetch_existing, DIST_DIR)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _local_episodes()


@app.post("/api/generate")
async def start_generation():
    if _job["running"]:
        raise HTTPException(409, "Une génération est déjà en cours")

    _job.update(running=True, log=[], result=None)

    async def _run():
        _job["log"].append("Récupération de l'historique…")
        try:
            await asyncio.to_thread(publish.fetch_existing, DIST_DIR)
            _job["log"].append("Collecte des flux RSS et synthèse vocale…")
            result = await generate_episode(load_config())
            _job["result"] = {
                "ok": result.ok,
                "reason": result.reason,
                "episode_id": result.episode_id,
                "duration": result.duration,
                "size": result.size,
                "titles": result.titles,
                "warnings": result.warnings,
                "ai_used": result.ai_used,
            }
            _job["log"].append("Terminé ✅" if result.ok else f"Aucun épisode : {result.reason}")
        except Exception as exc:  # le dashboard ne doit jamais crasher
            _job["result"] = {"ok": False, "reason": f"{exc.__class__.__name__} : {exc}"}
            _job["log"].append(f"Erreur : {exc}")
        finally:
            _job["running"] = False

    asyncio.create_task(_run())
    return {"ok": True}


@app.get("/api/generate/status")
def generation_status():
    return {"running": _job["running"], "log": _job["log"], "result": _job["result"]}


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
    if not any((DIST_DIR / "episodes").glob("*.json")):
        raise HTTPException(400, "Aucun épisode à publier — génère-en un d'abord")
    await _git_step(publish.publish_dist, DIST_DIR, "publication depuis le dashboard")
    return {"ok": True, "message": "Épisodes publiés sur GitHub Pages ✓"}


@app.post("/api/trigger")
async def trigger_workflow():
    await _git_step(publish.trigger_workflow)
    return {"ok": True, "message": "Workflow GitHub Actions déclenché 🚀"}


@app.get("/api/qr.png")
def feed_qr_png():
    """QR code du flux RSS : à scanner depuis le lecteur de podcast du téléphone."""
    config = load_config()
    if not config.feed_url:
        raise HTTPException(404, "Flux pas encore configuré (lance `myop setup`)")
    img = qrcode.make(config.feed_url, box_size=8, border=2)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")
