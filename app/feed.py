"""Flux RSS podcast (un par show) et page publique d'abonnement.

- la 1ʳᵉ émission activée est servie sur podcast.xml (rétro-compatible)
- les autres sur podcast-<id>.xml
- la page d'accueil GitHub Pages offre l'abonnement en un clic (Apple,
  Overcast, Pocket Casts), le QR code et un lecteur web complet
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from feedgen.feed import FeedGenerator


def load_episode_metas(dist_dir: Path, show_id: str) -> list[dict]:
    """Métadonnées des épisodes d'un show (dist/episodes/<show>/*.json)."""
    episodes_dir = dist_dir / "episodes" / show_id
    if not episodes_dir.exists():
        # Rétro-compat : épisodes à la racine = show historique « matin »
        if show_id == "matin":
            episodes_dir = dist_dir / "episodes"
        else:
            return []
    metas = []
    for meta_file in episodes_dir.glob("*.json"):
        try:
            metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    metas.sort(key=lambda m: m.get("id", ""), reverse=True)
    return metas


def feed_filename(config, show) -> str:
    """Nom du fichier de flux : podcast.xml pour la 1ʳᵉ émission activée."""
    first = next((s for s in config.shows if s.enabled), None)
    if first and show.id == first.id:
        return "podcast.xml"
    return f"podcast-{show.id}.xml"


def _duration_mmss(seconds: int) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def build_feed(config, show, episodes: list[dict], base_url: str) -> str:
    """Construit le XML du flux d'une émission."""
    fg = FeedGenerator()
    fg.load_extension("podcast")
    base = base_url.rstrip("/") + "/"

    first = next((s for s in config.shows if s.enabled), None)
    is_first = bool(first and show.id == first.id)
    cover = "cover.png" if is_first else f"cover-{show.id}.png"
    feed_file = feed_filename(config, show)

    fg.id(f"{base}{feed_file}")
    fg.title(show.title)
    fg.description(show.description)
    fg.language(config.language[:2])
    fg.link(href=base, rel="alternate")
    fg.link(href=f"{base}{feed_file}", rel="self")

    fg.podcast.itunes_author(config.author)
    fg.podcast.itunes_owner(name=config.author, email=config.email)
    fg.podcast.itunes_category(config.category or "News")
    fg.podcast.itunes_image(f"{base}{cover}")
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_subtitle("Émission générée par MYOP")

    latest = datetime(2020, 1, 1, tzinfo=timezone.utc)
    for meta in episodes:
        entry = fg.add_entry()
        entry.id(f"myop-{show.id}-{meta['id']}")  # guid stable
        entry.title(meta.get("title", meta["id"]))
        entry.description(meta.get("description", ""))
        entry.link(href=f"{base}episodes/{show.id}/{meta['id']}.mp3")
        pub = datetime.fromisoformat(meta["pubDate"])
        entry.pubDate(pub)
        entry.enclosure(
            url=f"{base}episodes/{show.id}/{meta['id']}.mp3",
            length=str(meta.get("size", 0)),
            type="audio/mpeg",
        )
        entry.podcast.itunes_duration(_duration_mmss(meta.get("duration", 0)))
        if pub > latest:
            latest = pub

    fg.updated(latest)
    return fg.rss_str(pretty=True).decode("utf-8")


def write_feed(config, show, dist_dir: Path) -> Path:
    """Écrit le flux d'une émission à partir des métadonnées présentes."""
    base = config.github.pages_base
    if not base:
        raise RuntimeError(
            "URL GitHub Pages inconnue : lance `myop setup` (ou configure github.pages_base)."
        )
    episodes = load_episode_metas(dist_dir, show.id)
    xml = build_feed(config, show, episodes, base)
    out = dist_dir / feed_filename(config, show)
    out.write_text(xml, encoding="utf-8")
    return out


# ------------------------------------------------------------ page publique ---

def _shows_json(config) -> str:
    """Données des émissions pour le lecteur web (fetch client des flux)."""
    data = []
    first = next((s for s in config.shows if s.enabled), None)
    for show in config.shows:
        if not show.enabled:
            continue
        is_first = bool(first and show.id == first.id)
        data.append(
            {
                "id": show.id,
                "title": show.title,
                "description": show.description,
                "feed": feed_filename(config, show),
                "cover": "cover.png" if is_first else f"cover-{show.id}.png",
            }
        )
    return json.dumps(data, ensure_ascii=False)


def write_index(config, dist_dir: Path) -> None:
    """Page d'accueil GitHub Pages : abonnement one-tap + QR + lecteur web."""
    import base64
    import io

    import qrcode

    shows = [s for s in config.shows if s.enabled]
    if not shows:
        return
    first = shows[0]
    first_feed = config.feed_url(first) or "podcast.xml"
    analytics = ""
    if config.analytics.url:
        safe = html.escape(config.analytics.url, quote=True)
        analytics = f'<script data-goatcounter="{safe}" async src="//gc.zgo.at/count.js"></script>'

    qr_img = qrcode.make(first_feed, box_size=8, border=2)
    buffer = io.BytesIO()
    qr_img.save(buffer, format="PNG")
    qr_data = base64.b64encode(buffer.getvalue()).decode()

    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(config.author)} — podcasts MYOP</title>
<style>
 :root {{ --bg1:#121430; --bg2:#582c82; --text:#f0eefb; --muted:#b9b2d8; --acc:#9fd0ff; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        background:linear-gradient(160deg,var(--bg1),var(--bg2) 90%); background-attachment:fixed;
        color:var(--text); min-height:100vh; }}
 .wrap {{ max-width:880px; margin:0 auto; padding:32px 20px 80px; }}
 header.hero {{ text-align:center; padding:36px 0 8px; }}
 .hero img {{ width:150px; border-radius:20px; box-shadow:0 12px 40px rgba(0,0,0,.45); }}
 .hero h1 {{ margin:18px 0 4px; font-size:2rem; }}
 .hero p {{ color:var(--muted); margin:.2em 0; }}
 .show {{ background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.12);
         border-radius:20px; padding:24px; margin:22px 0; }}
 .show-head {{ display:flex; gap:18px; align-items:center; flex-wrap:wrap; }}
 .show-head img {{ width:96px; height:96px; border-radius:14px; object-fit:cover; }}
 .show h2 {{ margin:0; font-size:1.3rem; }}
 .show .desc {{ color:var(--muted); margin:.4em 0 0; max-width:520px; }}
 .apps {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }}
 .apps a, .apps button {{ text-decoration:none; cursor:pointer; font-size:.92rem;
   padding:10px 16px; border-radius:12px; border:1px solid rgba(255,255,255,.2);
   background:rgba(255,255,255,.1); color:var(--text); }}
 .apps a.primary {{ background:linear-gradient(120deg,var(--acc),#c39bff); color:#121430; font-weight:700; border:none; }}
 .apps a:hover, .apps button:hover {{ filter:brightness(1.15); }}
 .sub {{ display:flex; gap:18px; margin-top:16px; align-items:center; flex-wrap:wrap; }}
 .sub .url {{ font-family:ui-monospace,monospace; font-size:.8rem; color:var(--acc);
   background:rgba(0,0,0,.3); padding:8px 12px; border-radius:10px; word-break:break-all; }}
 .sub img {{ background:#fff; padding:8px; border-radius:12px; width:120px; }}
 .eps {{ margin-top:14px; }}
 .ep {{ display:flex; gap:14px; align-items:center; padding:12px 4px;
       border-bottom:1px solid rgba(255,255,255,.08); }}
 .ep:last-child {{ border:none; }}
 .ep .meta {{ flex:1; min-width:0; }}
 .ep .meta .desc {{ color:var(--muted); font-size:.8rem; white-space:nowrap;
    overflow:hidden; text-overflow:ellipsis; }}
 .ep audio {{ width:230px; height:34px; }}
 .badge {{ color:var(--muted); font-size:.75rem; white-space:nowrap; }}
 footer {{ text-align:center; color:var(--muted); font-size:.8rem; margin-top:36px; }}
 footer a {{ color:var(--acc); }}
</style></head><body><div class="wrap">
<header class="hero">
 <img src="cover.png" alt="pochette">
 <h1>Les podcasts de {html.escape(config.author)}</h1>
 <p>Générés chaque jour par MYOP — ta radio personnelle</p>
</header>
<div id="shows"></div>
<footer>Fait avec <a href="https://github.com/rlacotte/myop">MYOP — My Own Podcast</a>{analytics}</footer>
</div>
<script>
const SHOWS = {_shows_json(config)};
const enc = encodeURIComponent;
function esc(s) {{ const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }}

async function loadShow(show) {{
  const card = document.createElement('section'); card.className = 'show';
  card.innerHTML = `
    <div class="show-head">
      <img src="${{show.cover}}" alt="">
      <div><h2>${{esc(show.title)}}</h2><p class="desc">${{esc(show.description)}}</p></div>
    </div>
    <div class="apps">
      <a class="primary" href="podcasts://${{location.host}}${{location.pathname}}${{show.feed}}">🎧 Apple Podcasts</a>
      <a href="https://overcast.fm/paste?url=${{enc(location.origin + location.pathname + show.feed)}}" target="_blank">Overcast</a>
      <a href="pktc://subscribe/${{location.origin + location.pathname + show.feed}}/${{enc(location.origin + location.pathname + show.feed)}}">Pocket Casts</a>
      <button onclick="navigator.clipboard.writeText(location.origin + location.pathname + show.feed).then(()=>this.textContent='✓ Copié')">Copier l'URL</button>
    </div>
    <div class="sub"><span class="url">${{location.origin}}${{location.pathname}}${{show.feed}}</span></div>
    <div class="eps"><p class="badge">chargement des épisodes…</p></div>`;
  const eps = card.querySelector('.eps');
  try {{
    const xml = await (await fetch(show.feed)).text();
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    const items = [...doc.querySelectorAll('item')].slice(0, 15);
    eps.innerHTML = '';
    for (const item of items) {{
      const enclosure = item.querySelector('enclosure');
      const date = new Date(item.querySelector('pubDate').textContent);
      const row = document.createElement('div'); row.className = 'ep';
      row.innerHTML = `
        <div class="meta">
          <strong>${{esc(item.querySelector('title').textContent)}}</strong>
          <div class="desc">${{esc(item.querySelector('description').textContent)}}</div>
        </div>
        <span class="badge">${{date.toLocaleDateString('fr-FR')}}</span>
        ${{enclosure ? `<audio controls preload="none" src="${{enclosure.getAttribute('url')}}"></audio>` : ''}}`;
      eps.append(row);
    }}
    if (!items.length) eps.innerHTML = '<p class="badge">aucun épisode pour l\\'instant</p>';
  }} catch (e) {{
    eps.innerHTML = '<p class="badge">flux indisponible pour l\\'instant</p>';
  }}
  return card;
}}

(async () => {{
  const box = document.getElementById('shows');
  for (const show of SHOWS) box.append(await loadShow(show));
}})();
</script>
</body></html>"""
    (dist_dir / "index.html").write_text(page, encoding="utf-8")
