"""Vérification en direct des flux RSS candidats (une seule fois, hors app)."""

import asyncio
import feedparser
import httpx

CANDIDATES = {
    "Général": [
        ("Le Monde — À la une", "https://www.lemonde.fr/rss/une.xml"),
        ("20 Minutes — Une", "https://www.20minutes.fr/feeds/rss-une.xml"),
        ("France 24 — Actualités", "https://www.france24.com/fr/rss"),
        ("Ouest-France — À la une", "https://www.ouest-france.fr/rss-en-continu.xml"),
        ("Libération — Une", "https://www.liberation.fr/arc/outboundfeeds/rss/"),
    ],
    "France / politique": [
        ("Le Monde — Politique", "https://www.lemonde.fr/politique/rss_full.xml"),
        ("franceinfo — Politique", "https://www.francetvinfo.fr/politique.rss"),
        ("Public Sénat", "https://www.publicsenat.fr/rss.xml"),
    ],
    "International": [
        ("Le Monde — International", "https://www.lemonde.fr/international/rss_full.xml"),
        ("RFI — Monde", "https://www.rfi.fr/fr/rss"),
        ("Courrier international", "https://www.courrierinternational.com/feed.xml"),
        ("DW (français)", "https://rss.dw.com/rdf/rss-fr-all"),
    ],
    "Économie / finance": [
        ("Le Monde — Économie", "https://www.lemonde.fr/economie/rss_full.xml"),
        ("La Tribune — Actualités", "https://www.latribune.fr/rss/rubriques/actualite.html"),
        ("Les Échos — Économie", "https://services.lesechos.fr/rss/les-echos-economie.xml"),
        ("Investing.com France", "https://fr.investing.com/rss/news.rss"),
    ],
    "Tech / numérique": [
        ("NextINpact", "https://www.nextinpact.com/rss"),
        ("Numerama", "https://www.numerama.com/feed/"),
        ("01net — Actualités", "https://www.01net.com/actualites/feed/"),
        ("Clubic — News", "https://www.clubic.com/feed/news.rss"),
        ("Frandroid", "https://www.frandroid.com/feed"),
        ("Mac4Ever", "https://www.mac4ever.com/rss/actus"),
    ],
    "Science": [
        ("Le Monde — Sciences", "https://www.lemonde.fr/sciences/rss_full.xml"),
        ("CNRS — Le Journal", "https://lejournal.cnrs.fr/rss"),
        ("Futura Sciences", "https://www.futura-sciences.com/rss/actualites.xml"),
        ("Maxi Sciences", "https://www.maxisciences.com/rss.xml"),
    ],
    "Culture / médias": [
        ("France Culture", "https://www.radiofrance.fr/franceculture/rss"),
        ("Le Monde — Livres", "https://www.lemonde.fr/livres/rss_full.xml"),
        ("Les Inrockuptibles", "https://www.lesinrocks.com/feed/"),
        ("Télérama", "https://www.telerama.fr/rss.xml"),
    ],
    "Sport": [
        ("L'Équipe — Actualités", "https://www.lequipe.fr/rss/actu_actualites.xml"),
        ("franceinfo — Sport", "https://www.francetvinfo.fr/sport.rss"),
        ("Eurosport France", "https://www.eurosport.fr/rss.xml"),
    ],
    "Environnement": [
        ("Le Monde — Planète", "https://www.lemonde.fr/planete/rss_full.xml"),
        ("Reporterre", "https://reporterre.net/spip.php?page=backend"),
    ],
    "Santé": [
        ("Le Quotidien du Médecin", "https://www.lequotidiendumedecin.fr/rss.xml"),
        ("Vidal — Actualités", "https://www.vidal.fr/rss/actualites.xml"),
    ],
    "Crypto": [
        ("Journal du Coin", "https://journalducoin.com/feed/"),
        ("Cointribune", "https://cointribune.com/feed/"),
    ],
    "Idées / analyse": [
        ("Le Monde — Idées", "https://www.lemonde.fr/idees/rss_full.xml"),
        ("AOC", "https://aoc.media/feed/"),
    ],
}


async def check(client, name, url):
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        entries = len(parsed.entries)
        title = (parsed.feed.get("title") or name).strip()[:45]
        if entries >= 3:
            return (name, url, title, entries, "OK")
        return (name, url, title, entries, "VIDE/INVALIDE")
    except Exception as exc:
        return (name, url, "—", 0, exc.__class__.__name__)


async def main():
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 myop/0.1"}, timeout=12, follow_redirects=True
    ) as client:
        tasks = [check(client, n, u) for cat, feeds in CANDIDATES.items() for n, u in feeds]
        results = await asyncio.gather(*tasks)

    for (name, url, title, entries, status), (cat, _) in zip(
        results, [(c, f) for c, feeds in CANDIDATES.items() for f in feeds]
    ):
        mark = "✅" if status == "OK" else "❌"
        print(f"{mark} [{cat}] {name} — {entries} items ({title})")


asyncio.run(main())
