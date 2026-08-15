"""Flux RSS podcast (un par show) et page publique d'abonnement.

- la 1ʳᵉ émission activée est servie sur podcast.xml (rétro-compatible)
- les autres sur podcast-<id>.xml
- la page d'accueil GitHub Pages offre l'abonnement en un clic (Apple,
  Overcast, Pocket Casts), le QR code et un lecteur web complet
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from feedgen.feed import FeedGenerator

# Espace de noms Podcasting 2.0 : feedgen ne le connaît pas, on l'ajoute après
# coup plutôt que d'écrire le flux à la main.
PODCAST_NS = "https://podcastindex.org/namespace/1.0"
_ITEM = re.compile(r"<item>.*?</item>", re.DOTALL)
_ENCLOSURE_ID = re.compile(r'<enclosure url="[^"]*/episodes/[^/]+/([^"/]+)\.mp3"')


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
        # « append » : sans cela feedgen empile en tête et le flux sort à
        # l'envers — les lecteurs qui gardent l'ordre du document, dont la
        # page publique, présentaient l'épisode le plus ancien en premier.
        entry = fg.add_entry(order="append")
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
    xml = fg.rss_str(pretty=True).decode("utf-8")
    return add_transcripts(xml, base, show.id, episodes)


def add_transcripts(xml: str, base: str, show_id: str, episodes: list[dict]) -> str:
    """Ajoute <podcast:transcript> aux épisodes qui en ont une."""
    with_transcript = {meta["id"] for meta in episodes if meta.get("transcript")}
    if not with_transcript:
        return xml

    def one(match: re.Match) -> str:
        block = match.group(0)
        found = _ENCLOSURE_ID.search(block)
        if not found or found.group(1) not in with_transcript:
            return block
        url = f"{base}episodes/{show_id}/{found.group(1)}.vtt"
        tag = f'    <podcast:transcript url="{url}" type="text/vtt" language="fr"/>\n'
        return block.replace("</item>", f"{tag}  </item>")

    xml = xml.replace("<rss ", f'<rss xmlns:podcast="{PODCAST_NS}" ', 1)
    return _ITEM.sub(one, xml)


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

def _shows_json(config, qr_by_show: dict[str, str] | None = None) -> str:
    """Données des émissions pour le lecteur web (fetch client des flux)."""
    qr_by_show = qr_by_show or {}
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
                "qr": qr_by_show.get(show.id, ""),
            }
        )
    return json.dumps(data, ensure_ascii=False)


def _qr_base64(url: str) -> str:
    """QR code d'un flux, en PNG base64 (aucun fichier à publier)."""
    import base64
    import io

    import qrcode

    buffer = io.BytesIO()
    qrcode.make(url, box_size=7, border=2).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def write_index(config, dist_dir: Path) -> None:
    """Page d'accueil GitHub Pages : abonnement one-tap + QR + lecteur web."""
    shows = [s for s in config.shows if s.enabled]
    if not shows:
        return
    analytics = ""
    if config.analytics.url:
        safe = html.escape(config.analytics.url, quote=True)
        analytics = f'<script data-goatcounter="{safe}" async src="//gc.zgo.at/count.js"></script>'

    # Un QR par émission : on se scanne son flux depuis le téléphone
    qr_by_show = {
        show.id: _qr_base64(config.feed_url(show) or feed_filename(config, show))
        for show in shows
    }

    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{html.escape(config.author)} — podcasts MYOP</title>
<meta name="description" content="Podcasts quotidiens generes par MYOP.">
<style>
 :root {{
   --paper:#faf8f5; --surface:#fff; --sunken:#f4f1ec; --line:#e7e1d7; --line-strong:#d5cdc0;
   --ink:#1a1714; --ink-2:#4a443c; --ink-3:#8a8276;
   --accent:#e4572e; --accent-ink:#b83c17; --accent-soft:#fdeee8;
   --cool:#14615c; --cool-soft:#e6f1ef;
   --serif:ui-serif,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
   --sans:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,Helvetica,sans-serif;
   --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
 }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; background:var(--paper); color:var(--ink); font-family:var(--sans);
        font-size:16px; line-height:1.55; -webkit-font-smoothing:antialiased; }}
 ::selection {{ background:var(--accent-soft); }}
 .wrap {{ max-width:760px; margin:0 auto; padding:0 22px 96px; }}

 header.hero {{ padding:72px 0 40px; border-bottom:1px solid var(--line); margin-bottom:38px; }}
 .eyebrow {{ font-size:.72rem; letter-spacing:.14em; text-transform:uppercase;
            color:var(--accent-ink); font-weight:600; margin:0; }}
 h1 {{ font-family:var(--serif); font-size:clamp(2.4rem,7vw,3.4rem); line-height:1.05;
      letter-spacing:-.028em; font-weight:600; margin:.28em 0 .2em; }}
 header.hero p.sub {{ color:var(--ink-2); margin:0; font-size:1.05rem; max-width:46ch; }}

 .show {{ margin-bottom:56px; }}
 .show-head {{ display:flex; gap:22px; align-items:flex-start; }}
 .show-head img.cover {{ width:104px; height:104px; border-radius:14px; object-fit:cover; flex:none;
   border:1px solid var(--line); box-shadow:0 2px 4px rgba(26,23,20,.05),0 18px 40px rgba(26,23,20,.09); }}
 .show h2 {{ font-family:var(--serif); font-size:1.7rem; letter-spacing:-.02em;
            font-weight:600; margin:0 0 4px; }}
 .show .desc {{ color:var(--ink-2); margin:0; font-size:.96rem; }}

 .apps {{ display:flex; gap:9px; flex-wrap:wrap; margin:22px 0 0; }}
 .apps a, .apps button {{ font:inherit; font-size:.88rem; font-weight:500; cursor:pointer;
   text-decoration:none; padding:9px 16px; border-radius:10px;
   border:1px solid var(--line-strong); background:var(--surface); color:var(--ink); }}
 .apps a:hover, .apps button:hover {{ background:var(--sunken); }}
 .apps a.primary {{ background:var(--accent); border-color:var(--accent); color:#fff; }}
 .apps a.primary:hover {{ background:var(--accent-ink); border-color:var(--accent-ink); }}

 .sub-row {{ display:flex; gap:18px; align-items:center; margin-top:18px; flex-wrap:wrap; }}
 .sub-row img.qr {{ width:96px; border-radius:10px; border:1px solid var(--line);
                   background:#fff; padding:6px; flex:none; }}
 .url {{ font-family:var(--mono); font-size:.76rem; color:var(--cool); background:var(--cool-soft);
        border:1px solid #cfe3e0; border-radius:10px; padding:9px 12px; word-break:break-all; flex:1; min-width:220px; }}

 .eps {{ margin-top:30px; border-top:1px solid var(--line); }}
 .ep {{ display:flex; gap:16px; align-items:center; padding:16px 0; border-bottom:1px solid var(--line); }}
 .ep .meta {{ flex:1; min-width:0; }}
 .ep .t {{ font-weight:600; font-size:1rem; }}
 .ep .d {{ color:var(--ink-3); font-size:.83rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
 .ep .links {{ margin-top:5px; display:flex; gap:12px; font-size:.79rem; }}
 .ep .links a {{ color:var(--cool); text-decoration:none; border-bottom:1px solid #bcd8d4; }}
 .ep audio {{ width:230px; height:34px; flex:none; }}
 .ep .date {{ color:var(--ink-3); font-size:.79rem; white-space:nowrap; }}
 .note {{ color:var(--ink-3); font-size:.87rem; padding:20px 0; }}

 footer {{ border-top:1px solid var(--line); padding-top:24px; color:var(--ink-3); font-size:.83rem; }}
 footer a {{ color:var(--ink-2); }}

 @media (max-width:620px) {{
   header.hero {{ padding:46px 0 30px; }}
   .show-head {{ gap:16px; }}
   .show-head img.cover {{ width:78px; height:78px; }}
   .ep {{ flex-wrap:wrap; }}
   .ep audio {{ width:100%; }}
 }}
</style></head><body><div class="wrap">
<header class="hero">
 <p class="eyebrow">Radio personnelle</p>
 <h1>Les podcasts de {html.escape(config.author)}</h1>
 <p class="sub">Un nouvel épisode chaque jour, écrit et monté automatiquement.
   Abonne-toi une fois : la suite arrive toute seule.</p>
</header>
<div id="shows"></div>
<footer>Fait avec <a href="https://github.com/rlacotte/myop">MYOP — My Own Podcast</a>{analytics}</footer>
</div>
<script>
const SHOWS = {_shows_json(config, qr_by_show)};
const enc = encodeURIComponent;
function esc(s) {{ const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }}
const feedUrl = (show) => location.origin + location.pathname.replace(/index\.html$/, '') + show.feed;

async function loadShow(show) {{
  const url = feedUrl(show);
  const card = document.createElement('section'); card.className = 'show';
  card.innerHTML = `
    <div class="show-head">
      <img class="cover" src="${{show.cover}}" alt="">
      <div>
        <h2>${{esc(show.title)}}</h2>
        <p class="desc">${{esc(show.description)}}</p>
        <div class="apps">
          <a class="primary" href="podcasts://${{url.replace(/^https?:\/\//, '')}}">Apple Podcasts</a>
          <a href="https://overcast.fm/paste?url=${{enc(url)}}" target="_blank" rel="noopener">Overcast</a>
          <a href="pktc://subscribe/${{url.replace(/^https?:\/\//, '')}}">Pocket Casts</a>
          <button type="button">Copier l'URL</button>
        </div>
      </div>
    </div>
    <div class="sub-row">
      ${{show.qr ? `<img class="qr" alt="QR code du flux" src="data:image/png;base64,${{show.qr}}">` : ''}}
      <span class="url">${{esc(url)}}</span>
    </div>
    <div class="eps"><p class="note">Chargement des épisodes…</p></div>`;

  card.querySelector('.apps button').addEventListener('click', (event) => {{
    navigator.clipboard.writeText(url).then(() => (event.target.textContent = 'Copié ✓'));
  }});

  const eps = card.querySelector('.eps');
  try {{
    const xml = await (await fetch(show.feed)).text();
    const doc = new DOMParser().parseFromString(xml, 'text/xml');
    const items = [...doc.querySelectorAll('item')].slice(0, 15);
    eps.innerHTML = '';
    for (const item of items) {{
      const enclosure = item.querySelector('enclosure');
      const date = new Date(item.querySelector('pubDate').textContent);
      // Transcription : on sert la version lisible, pas le fichier de sous-titres
      const vtt = item.getElementsByTagName('podcast:transcript')[0];
      const text = vtt ? vtt.getAttribute('url').replace(/\.vtt$/, '.txt') : null;
      const row = document.createElement('div'); row.className = 'ep';
      row.innerHTML = `
        <div class="meta">
          <div class="t">${{esc(item.querySelector('title').textContent)}}</div>
          <div class="d">${{esc(item.querySelector('description').textContent)}}</div>
          ${{text ? `<div class="links"><a href="${{text}}">Lire la transcription</a></div>` : ''}}
        </div>
        <span class="date">${{date.toLocaleDateString('fr-FR', {{ day: 'numeric', month: 'short' }})}}</span>
        ${{enclosure ? `<audio controls preload="none" src="${{enclosure.getAttribute('url')}}"></audio>` : ''}}`;
      eps.append(row);
    }}
    if (!items.length) eps.innerHTML = '<p class="note">Aucun épisode publié pour le moment.</p>';
  }} catch (e) {{
    eps.innerHTML = '<p class="note">Flux momentanément indisponible.</p>';
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
