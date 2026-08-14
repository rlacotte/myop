"""Bibliothèque de sources RSS intégrée, prête à activer depuis le dashboard.

Tous ces flux ont été vérifiés en direct (items présents, pas de redirection
cassée). Le bouton « Tester » du dashboard permet de re-vérifier à tout moment.
"""

from __future__ import annotations

LIBRARY: dict[str, list[dict]] = {
    "Généralistes": [
        {"name": "Le Monde — À la une", "url": "https://www.lemonde.fr/rss/une.xml"},
        {"name": "franceinfo — Titres", "url": "https://www.francetvinfo.fr/titres.rss"},
        {"name": "Europe 1 — Actualités", "url": "https://www.europe1.fr/rss.xml"},
        {"name": "20 Minutes — Une", "url": "https://www.20minutes.fr/feeds/rss-une.xml"},
        {"name": "France 24 — Actualités", "url": "https://www.france24.com/fr/rss"},
        {"name": "Libération — Une", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/"},
        {"name": "Ouest-France — À la une", "url": "https://www.ouest-france.fr/rss-en-continu.xml"},
    ],
    "Politique & société": [
        {"name": "Le Monde — Politique", "url": "https://www.lemonde.fr/politique/rss_full.xml"},
        {"name": "franceinfo — Politique", "url": "https://www.francetvinfo.fr/politique.rss"},
        {"name": "Le Monde — Société", "url": "https://www.lemonde.fr/societe/rss_full.xml"},
    ],
    "International": [
        {"name": "Le Monde — International", "url": "https://www.lemonde.fr/international/rss_full.xml"},
        {"name": "RFI — Monde", "url": "https://www.rfi.fr/fr/rss"},
    ],
    "Économie & finance": [
        {"name": "Le Monde — Économie", "url": "https://www.lemonde.fr/economie/rss_full.xml"},
        {"name": "La Tribune — Actualités", "url": "https://www.latribune.fr/rss/rubriques/actualite.html"},
        {"name": "Investing.com — Marchés", "url": "https://fr.investing.com/rss/news.rss"},
    ],
    "Tech & numérique": [
        {"name": "NextINpact — Numérique", "url": "https://www.nextinpact.com/rss"},
        {"name": "Numerama", "url": "https://www.numerama.com/feed/"},
        {"name": "01net — Actualités", "url": "https://www.01net.com/actualites/feed/"},
        {"name": "Clubic — News", "url": "https://www.clubic.com/feed/news.rss"},
        {"name": "Frandroid", "url": "https://www.frandroid.com/feed"},
        {"name": "Le Monde — Big Browser", "url": "https://www.lemonde.fr/big-browser/rss_full.xml"},
    ],
    "Sciences": [
        {"name": "Le Monde — Sciences", "url": "https://www.lemonde.fr/sciences/rss_full.xml"},
        {"name": "CNRS — Le Journal", "url": "https://lejournal.cnrs.fr/rss"},
        {"name": "Futura Sciences", "url": "https://www.futura-sciences.com/rss/actualites.xml"},
        {"name": "Maxi Sciences", "url": "https://www.maxisciences.com/rss.xml"},
    ],
    "Culture & idées": [
        {"name": "France Culture — Idées", "url": "https://www.radiofrance.fr/franceculture/rss"},
        {"name": "Le Monde — Livres", "url": "https://www.lemonde.fr/livres/rss_full.xml"},
        {"name": "Les Inrocks", "url": "https://www.lesinrocks.com/feed/"},
        {"name": "Le Monde — Idées", "url": "https://www.lemonde.fr/idees/rss_full.xml"},
        {"name": "AOC — Analyse & opinion", "url": "https://aoc.media/feed/"},
    ],
    "Sport": [
        {"name": "L'Équipe — Cyclisme", "url": "https://dwh.lequipe.fr/api/edito/rss?path=/Cyclisme/"},
        {"name": "Le Monde — Sport", "url": "https://www.lemonde.fr/sport/rss_full.xml"},
        {"name": "20 Minutes — Sport", "url": "https://www.20minutes.fr/feeds/rss-sport.xml"},
    ],
    "Environnement": [
        {"name": "Le Monde — Planète", "url": "https://www.lemonde.fr/planete/rss_full.xml"},
        {"name": "Reporterre — Écologie", "url": "https://reporterre.net/spip.php?page=backend"},
    ],
    "Santé": [
        {"name": "Le Monde — Santé", "url": "https://www.lemonde.fr/sante/rss_full.xml"},
        {"name": "Le Quotidien du Médecin", "url": "https://www.lequotidiendumedecin.fr/rss.xml"},
    ],
    "Crypto": [
        {"name": "Journal du Coin", "url": "https://journalducoin.com/feed/"},
        {"name": "Cointribune", "url": "https://cointribune.com/feed/"},
    ],
    "International (traduit par l'IA)": [
        {"name": "The Guardian — World 🇬🇧", "url": "https://www.theguardian.com/world/rss"},
        {"name": "BBC News — World 🇬🇧", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
        {"name": "El País — Portada 🇪🇸", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"},
        {"name": "Al Jazeera — News 🇶🇦", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
        {"name": "SRF — Actualités 🇨🇭", "url": "https://www.srf.ch/news/bnf/rss/1646"},
        {"name": "Le Devoir 🇨🇦", "url": "https://www.ledevoir.com/rss/ledevoir.xml"},
        {"name": "Radio-Canada — International 🇨🇦", "url": "https://ici.radio-canada.ca/rss/4159"},
        {"name": "Euronews — Actualités", "url": "https://www.euronews.com/rss?level=theme&name=news"},
    ],
}


def library_urls() -> set[str]:
    """Toutes les URL du catalogue (comparaison avec la config active)."""
    return {feed["url"] for feeds in LIBRARY.values() for feed in feeds}
