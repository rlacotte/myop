"""Pipeline complet d'un épisode : collecte → script → voix → MP3 → flux.

Une « génération » concerne UNE émission (show). Le module expose aussi
build_draft() pour préparer le script sans le synthétiser (éditeur du
dashboard), puis render pour finaliser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import feedback as feedback_mod
from . import reading as reading_mod
from .chapters import write_chapters
from .config import Config, Show
from .ephemeris import ephemeris_text
from .feed import feed_filename, write_feed, write_index
from .script import PARIS, Segment, build_script, episode_description, episode_title
from .sources import fetch_items, title_tokens
from .transcript import write_transcript
from .tts import synthesize
from .weather import fetch_weather, weather_text

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"
SEEN_LIMIT = 3000  # taille max de l'historique de dédoublonnage
# Un sujet déjà traité ne revient pas avant quelques jours, même repris par un
# autre média sous un autre titre (l'historique par URL ne le voit pas passer).
TOPIC_MEMORY_DAYS = 3
TOPIC_LIMIT = 600


@dataclass
class GenerationResult:
    """Bilan d'une génération."""

    ok: bool
    show_id: str = ""
    reason: str = ""
    episode_id: str | None = None
    episode_path: Path | None = None
    duration: int = 0
    size: int = 0
    titles: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ai_used: bool = False
    chapter_titles: list[str] = field(default_factory=list)
    reading_count: int = 0


@dataclass
class Draft:
    """Script préparé (avant synthèse) — base de l'éditeur du dashboard."""

    show_id: str
    episode_id: str
    title: str
    description: str
    segments: list[Segment]
    titles: list[str]
    ai_used: bool
    warnings: list[str] = field(default_factory=list)
    # Contexte nécessaire au rendu final
    items_keys: list[str] = field(default_factory=list)  # pour l'historisation
    reading_items: list = field(default_factory=list)


def _seen_path(dist_dir: Path, show: Show) -> Path:
    return dist_dir / f"seen-{show.id}.json"


def load_seen(dist_dir: Path, show: Show) -> set[str]:
    """Historique des articles déjà diffusés (avec héritage de l'ancien format)."""
    seen_file = _seen_path(dist_dir, show)
    if not seen_file.exists() and show.id == "matin":
        legacy = dist_dir / "seen.json"  # format mono-émission
        if legacy.exists():
            seen_file = legacy
    if not seen_file.exists():
        return set()
    try:
        return set(json.loads(seen_file.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(dist_dir: Path, show: Show, seen: set[str]) -> None:
    """Persiste l'historique, plafonnée pour rester légère."""
    kept = sorted(seen)[-SEEN_LIMIT:]
    seen_file = _seen_path(dist_dir, show)
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    seen_file.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------- mémoire des sujets --

def _topics_path(dist_dir: Path, show: Show) -> Path:
    return dist_dir / f"topics-{show.id}.json"


def _read_topics(dist_dir: Path, show: Show) -> list[str]:
    """Entrées « <date ISO> <mots du titre> », triées donc chronologiques."""
    path = _topics_path(dist_dir, show)
    if not path.exists():
        return []
    try:
        return [entry for entry in json.loads(path.read_text(encoding="utf-8")) if entry]
    except (json.JSONDecodeError, OSError, TypeError):
        return []


def load_topics(dist_dir: Path, show: Show, now: datetime) -> list[set[str]]:
    """Sujets diffusés ces derniers jours, en jeux de mots significatifs."""
    floor = (now.date() - timedelta(days=TOPIC_MEMORY_DAYS)).isoformat()
    topics = []
    for entry in _read_topics(dist_dir, show):
        date, _, words = entry.partition(" ")
        if date >= floor and words:
            topics.append(set(words.split()))
    return topics


def save_topics(dist_dir: Path, show: Show, titles: list[str], now: datetime) -> None:
    """Mémorise les sujets de l'épisode, en purgeant les plus anciens.

    Le format (date en préfixe, une chaîne par sujet) se fusionne avec
    l'historique publié par la même union triée que `seen-<show>.json`.
    """
    day = now.date().isoformat()
    floor = (now.date() - timedelta(days=TOPIC_MEMORY_DAYS)).isoformat()
    entries = {entry for entry in _read_topics(dist_dir, show) if entry[: len(floor)] >= floor}
    for title in titles:
        tokens = title_tokens(title)
        if tokens:
            entries.add(f"{day} {' '.join(sorted(tokens))}")
    path = _topics_path(dist_dir, show)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sorted(entries)[-TOPIC_LIMIT:], ensure_ascii=False), encoding="utf-8"
    )


def _load_font(size: int):
    """Police système pour les pochettes (fallback multi-OS)."""
    from PIL import ImageFont

    for candidate in [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",  # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux CI
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    try:
        return ImageFont.load_default(size=size)  # Pillow ≥ 10.1
    except TypeError:
        return ImageFont.load_default()


def make_cover(title: str, out_path: Path, subtitle: str = "ton briefing quotidien") -> Path:
    """Pochette 1400×1400 (titre sur fond dégradé) si absente."""
    from PIL import Image, ImageDraw

    if out_path.exists():
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    size = 1400
    image = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(image)
    # Dégradé vertical bleu nuit → violet
    top, bottom = (18, 20, 48), (88, 44, 130)
    for y in range(size):
        t = y / size
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    # Cercles décoratifs
    for cx, cy, r, alpha in [(1150, 260, 340, 40), (260, 1150, 420, 36), (700, 760, 900, 22)]:
        overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, alpha))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)

    draw.text((70, 120), "MYOP", fill=(150, 200, 255), font=_load_font(90))
    # Titre centré, retour à la ligne automatique
    font = _load_font(170)
    words = title.split()
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) > size - 140:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    y = (size - len(lines) * 200) // 2 + 40
    for text_line in lines[:3]:
        draw.text((70, y), text_line, fill=(255, 255, 255), font=font)
        y += 200
    draw.text((70, size - 130), subtitle, fill=(200, 190, 230), font=_load_font(64))

    image.save(out_path, "PNG")
    return out_path


async def _collect_day(
    config: Config, show: Show, dist_dir: Path, now: datetime, ignore_seen: bool = False
):
    """Collecte articles + météo + éphéméride + liste de lecture du jour."""
    feedback = feedback_mod.load_feedback(dist_dir)
    ranker = (lambda items: feedback_mod.apply_feedback(items, feedback)) if (
        feedback.source_scores or feedback.disliked_keywords
    ) else None

    seen = set() if ignore_seen else load_seen(dist_dir, show)
    recent_topics = [] if ignore_seen else load_topics(dist_dir, show, now)
    fetched = await fetch_items(
        show,
        now=now.astimezone(ZoneInfo("UTC")),
        seen=seen,
        ranker=ranker,
        recent_topics=recent_topics,
    )

    weather = await fetch_weather(show.weather_city) if show.weather_city else None
    weather_line = weather_text(weather) if weather else ""
    ephemeris_line = ephemeris_text(now) if show.ephemeris else ""
    reading_items = (
        reading_mod.peek_for_episode(dist_dir, config.reading.max_items)
        if config.reading.enabled
        else []
    )
    return fetched, weather, weather_line, ephemeris_line, reading_items


async def _compose_script(
    config: Config,
    show: Show,
    fetched,
    now: datetime,
    weather,
    weather_line: str,
    ephemeris_line: str,
    reading_items: list,
    warnings: list[str],
) -> tuple[list[Segment], bool]:
    """Script IA si activée et disponible, sinon script déterministe.

    L'IA ne doit jamais bloquer la production : tout échec retombe
    (avec avertissement) sur le script classique.
    """
    if config.ai.enabled:
        from .ai import ai_script, load_api_key

        if load_api_key(config):
            try:
                segments = await ai_script(
                    show,
                    config,
                    fetched.selected,
                    now=now,
                    weather_line=weather_line,
                    ephemeris_line=ephemeris_line,
                    reading_items=reading_items,
                )
            except Exception as exc:  # réseau, HTTP, quota… on continue sans IA
                warnings.append(
                    f"IA en échec ({exc.__class__.__name__}) → script déterministe"
                )
                segments = None
            if segments:
                return segments, True
            warnings.append("Réponse IA inutilisable → script déterministe")
        else:
            warnings.append(
                "IA activée mais clé absente (.openrouter_api_key) → script déterministe"
            )
    return (
        build_script(
            show,
            fetched.selected,
            now=now,
            weather=weather,
            weather_line=weather_line,
            ephemeris_line=ephemeris_line,
            reading_items=reading_items,
        ),
        False,
    )


async def build_draft(
    config: Config,
    show: Show,
    dist_dir: Path | None = None,
    *,
    now: datetime | None = None,
) -> Draft:
    """Prépare le script de l'épisode sans le synthétiser (éditeur dashboard)."""
    dist_dir = dist_dir or DIST_DIR
    now = now or datetime.now(tz=PARIS)
    fetched, weather, weather_line, ephemeris_line, reading_items = await _collect_day(
        config, show, dist_dir, now
    )
    warnings = [f"Source inaccessible — {e}" for e in fetched.errors]
    segments, ai_used = await _compose_script(
        config, show, fetched, now, weather, weather_line, ephemeris_line,
        reading_items, warnings,
    )
    return Draft(
        show_id=show.id,
        episode_id=now.astimezone(PARIS).date().isoformat(),
        title=episode_title(show, now),
        description=episode_description(fetched.selected[: show.num_headlines]),
        segments=segments,
        titles=[item.title for item in fetched.selected[: show.num_headlines]],
        ai_used=ai_used,
        warnings=warnings,
        items_keys=fetched.all_keys,
        reading_items=reading_items,
    )


def prune_episodes(dist_dir: Path, show_id: str, keep: int) -> list[str]:
    """Ne garde que les `keep` épisodes les plus récents d'une émission.

    Appelé avant l'écriture des flux : ce qui disparaît du disque disparaît
    du flux, et `publish_dist` répercute la coupe sur GitHub Pages.
    Les identifiants sont des dates ISO : l'ordre lexicographique suffit.
    """
    if keep <= 0:
        return []
    episodes_dir = dist_dir / "episodes" / show_id
    if not episodes_dir.exists():
        return []
    ids = sorted(path.stem for path in episodes_dir.glob("*.json"))
    dropped = ids[:-keep] if len(ids) > keep else []
    for episode_id in dropped:
        for suffix in (".json", ".mp3", ".vtt", ".txt"):
            (episodes_dir / f"{episode_id}{suffix}").unlink(missing_ok=True)
    return dropped


def _publish_statics(config: Config, dist_dir: Path) -> None:
    """Flux de toutes les émissions + pochettes + page publique."""
    first = next((s for s in config.shows if s.enabled), None)
    for show in config.shows:
        if not show.enabled:
            continue
        prune_episodes(dist_dir, show.id, config.publishing.keep_episodes)
        is_first = bool(first and show.id == first.id)
        cover_name = "cover.png" if is_first else f"cover-{show.id}.png"
        make_cover(show.title, dist_dir / cover_name)
        try:
            write_feed(config, show, dist_dir)
        except RuntimeError:  # pages_base absent : premier setup
            pass
    try:
        write_index(config, dist_dir)
    except RuntimeError:
        pass


async def generate_episode(
    config: Config,
    show: Show,
    dist_dir: Path | None = None,
    *,
    now: datetime | None = None,
    ignore_seen: bool = False,
    draft: Draft | None = None,
) -> GenerationResult:
    """Génère l'épisode du jour d'une émission et reconstruit tous les flux.

    `draft` : script préparé (voire édité à la main) via build_draft().
    """
    dist_dir = dist_dir or DIST_DIR
    now = now or datetime.now(tz=PARIS)
    result = GenerationResult(ok=False, show_id=show.id)
    episodes_dir = dist_dir / "episodes" / show.id
    episodes_dir.mkdir(parents=True, exist_ok=True)

    if draft is not None:
        all_keys = draft.items_keys
        segments, ai_used = draft.segments, draft.ai_used
        result.warnings = list(draft.warnings)
        reading_items = draft.reading_items
        titles = draft.titles
        description, title = draft.description, draft.title
    else:
        fetched, weather, weather_line, ephemeris_line, reading_items = await _collect_day(
            config, show, dist_dir, now, ignore_seen
        )
        result.warnings = [f"Source inaccessible — {e}" for e in fetched.errors]
        if not fetched.selected:
            result.reason = (
                "Aucun nouvel article dans les dernières 24 h "
                f"({len(fetched.errors)} source(s) en échec)."
            )
            return result
        segments, ai_used = await _compose_script(
            config, show, fetched, now, weather, weather_line, ephemeris_line,
            reading_items, result.warnings,
        )
        titles = [item.title for item in fetched.selected[: show.num_headlines]]
        description = episode_description(fetched.selected[: show.num_headlines])
        title = episode_title(show, now)
        all_keys = fetched.all_keys

    # Épisode du jour (une seule édition par date : regénérer remplace le fichier)
    episode_id = now.astimezone(PARIS).date().isoformat()
    mp3_path = episodes_dir / f"{episode_id}.mp3"
    synth = await synthesize(segments, show, config, mp3_path)
    result.warnings.extend(synth.warnings)
    if config.audio.chapters:
        write_chapters(mp3_path, synth.chapters)

    has_transcript = write_transcript(title, segments, synth.chapters, mp3_path)

    meta = {
        "id": episode_id,
        "title": title,
        "description": description,
        "pubDate": now.astimezone(PARIS).isoformat(),
        "duration": synth.duration_seconds,
        "size": mp3_path.stat().st_size,
        # Porté par la fiche : le flux se reconstruit sans relire le disque
        "transcript": has_transcript,
    }
    (episodes_dir / f"{episode_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Historisation : tout ce qui a été vu aujourd'hui ne reviendra pas demain
    save_seen(dist_dir, show, load_seen(dist_dir, show) | set(all_keys))
    # Les sujets traités aujourd'hui ne reviendront pas sous un autre titre
    save_topics(dist_dir, show, titles, now)
    # Les articles lus dans cet épisode quittent la file d'attente
    if reading_items:
        reading_mod.remove_urls(
            dist_dir, [getattr(item, "url", "") for item in reading_items]
        )

    _publish_statics(config, dist_dir)

    result.ok = True
    result.episode_id = episode_id
    result.episode_path = mp3_path
    result.duration = synth.duration_seconds
    result.size = meta["size"]
    result.titles = titles
    result.ai_used = ai_used
    result.chapter_titles = [chapter["title"] for chapter in synth.chapters]
    result.reading_count = len(reading_items)
    return result
