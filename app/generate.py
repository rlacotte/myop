"""Pipeline complet d'un épisode : collecte → script → voix → MP3 → flux."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config
from .feed import write_feed
from .script import PARIS, build_script, episode_description, episode_title
from .sources import fetch_items
from .tts import synthesize

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
SEEN_LIMIT = 3000  # taille max de l'historique de dédoublonnage


@dataclass
class GenerationResult:
    """Bilan d'une génération."""

    ok: bool
    reason: str = ""
    episode_id: str | None = None
    episode_path: Path | None = None
    duration: int = 0
    size: int = 0
    titles: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_seen(dist_dir: Path) -> set[str]:
    """Historique des articles déjà diffusés (clés stables)."""
    seen_file = dist_dir / "seen.json"
    if not seen_file.exists():
        return set()
    try:
        return set(json.loads(seen_file.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(dist_dir: Path, seen: set[str]) -> None:
    """Persiste l'historique, plafonnée pour rester légère."""
    kept = sorted(seen)[-SEEN_LIMIT:]
    seen_file = dist_dir / "seen.json"
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    seen_file.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")


def _load_font(size: int):
    """Police système pour la pochette (fallback multi-OS)."""
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


def make_cover(config: Config, out_path: Path) -> Path:
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
    words = config.title.split()
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
    draw.text((70, size - 130), "ton briefing quotidien", fill=(200, 190, 230), font=_load_font(64))

    image.save(out_path, "PNG")
    return out_path


def write_index(config: Config, dist_dir: Path) -> None:
    """Mini page d'accueil GitHub Pages : lien d'abonnement + QR code."""
    import base64
    import io

    import qrcode

    feed_url = config.feed_url
    qr_data = ""
    if feed_url:
        img = qrcode.make(feed_url, box_size=8, border=2)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        qr_data = base64.b64encode(buffer.getvalue()).decode()
        qr_tag = f'<img class="qr" alt="QR code d’abonnement" src="data:image/png;base64,{qr_data}">'
        link = f'<p><a href="podcast.xml">{feed_url}</a></p>'
    else:
        qr_tag, link = "", "<p>Flux pas encore publié — lance <code>myop setup</code>.</p>"

    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{config.title}</title>
<style>
 body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        background:linear-gradient(160deg,#121430,#582c82); color:#fff; min-height:100vh;
        display:flex; align-items:center; justify-content:center; }}
 .card {{ text-align:center; padding:48px; max-width:520px; }}
 h1 {{ font-size:2.4rem; margin:.2em 0 .4em; }}
 a {{ color:#9fd0ff; word-break:break-all; }}
 .qr {{ background:#fff; padding:12px; border-radius:12px; margin:20px 0; width:220px; }}
 p {{ color:#d8d2ee; line-height:1.5; }}
 code {{ background:rgba(255,255,255,.15); padding:2px 6px; border-radius:6px; }}
</style></head>
<body><div class="card">
 <img src="cover.png" alt="pochette" style="width:180px;border-radius:16px">
 <h1>{config.title}</h1>
 <p>{config.description}</p>
 {link}
 {qr_tag}
 <p>Scan le QR code ou copie l'URL dans ton lecteur de podcast<br>
 (Apple Podcasts, Overcast, Pocket Casts…).</p>
</div></body></html>"""
    (dist_dir / "index.html").write_text(html, encoding="utf-8")


async def generate_episode(
    config: Config,
    dist_dir: Path | None = None,
    *,
    now: datetime | None = None,
) -> GenerationResult:
    """Génère l'épisode du jour et reconstruit le flux. Aucun réseau côté publication."""
    dist_dir = dist_dir or DIST_DIR
    now = now or datetime.now(tz=PARIS)
    episodes_dir = dist_dir / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    seen = load_seen(dist_dir)
    fetched = await fetch_items(config, now=now.astimezone(ZoneInfo("UTC")), seen=seen)
    result = GenerationResult(
        ok=False, warnings=[f"Source inaccessible — {e}" for e in fetched.errors]
    )

    if not fetched.selected:
        result.reason = (
            "Aucun nouvel article dans les dernières 24 h "
            f"({len(fetched.errors)} source(s) en échec)."
        )
        return result

    # Épisode du jour (une seule édition par date : regénérer remplace le fichier)
    episode_id = now.astimezone(PARIS).date().isoformat()
    segments = build_script(config, fetched.selected, now=now)
    mp3_path = episodes_dir / f"{episode_id}.mp3"
    mp3_path, duration = await synthesize(segments, config.voice, mp3_path)

    meta = {
        "id": episode_id,
        "title": episode_title(now),
        "description": episode_description(fetched.selected[: config.num_headlines]),
        "pubDate": now.astimezone(PARIS).isoformat(),
        "duration": duration,
        "size": mp3_path.stat().st_size,
    }
    (episodes_dir / f"{episode_id}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Historisation : tout ce qui a été vu aujourd'hui ne reviendra pas demain
    save_seen(dist_dir, seen | set(fetched.all_keys))

    # Flux + pochette + page d'accueil
    make_cover(config, dist_dir / "cover.png")
    if config.feed_url:
        write_feed(config, dist_dir)
        write_index(config, dist_dir)

    result.ok = True
    result.episode_id = episode_id
    result.episode_path = mp3_path
    result.duration = duration
    result.size = meta["size"]
    result.titles = [item.title for item in fetched.selected[: config.num_headlines]]
    return result
