"""Rédaction du script assistée par IA (optionnelle), via OpenRouter.

Le modèle réécrit les articles collectés en briefing radio naturel.
En cas d'échec ou d'absence de clé, le pipeline retombe sur le script
déterministe (app/script.py) : l'épisode part toujours en production.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

from .config import Config
from .script import PARIS, Segment, format_date_fr
from .sources import FeedItem

ROOT = Path(__file__).resolve().parent.parent
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "Tu es rédacteur en chef d'un flash d'actualité radiophonique français, "
    "écrit pour être lu à voix haute par une synthèse vocale. "
    "Style : clair, vivant, factuel — jamais sensationnaliste. "
    "Tu ne cites aucune URL, aucun emoji, aucun sigle imprononçable non développé. "
    "Tu t'appuies STRICTEMENT sur les articles fournis : aucun fait inventé, aucune date ajoutée."
)

# Débits par type de segment (repris de la config, l'IA ne les choisit pas)
KIND_RATES = {"intro": "intro_rate", "headlines": "brief_rate", "brief": "brief_rate", "outro": "intro_rate"}


def load_api_key(config: Config) -> str | None:
    """Clé depuis le fichier local (non versionné) ou la variable d'environnement."""
    key_file = ROOT / config.ai.key_file
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    return os.environ.get("OPENROUTER_API_KEY") or None


def build_user_prompt(config: Config, items: list[FeedItem], now: datetime) -> str:
    """Consigne détaillée + articles sourcés, réponse attendue en JSON strict."""
    date_str = format_date_fr(now)
    articles = "\n".join(
        f"{i}. {item.title}\n   Source : {item.source_name}\n"
        f"   Résumé : {item.summary[: config.max_brief_chars] or '(pas de résumé)'}"
        for i, item in enumerate(items[: config.num_headlines], start=1)
    )
    briefs = (
        f"- un segment intro (kind \"intro\") : souhait de bonjour, date « {date_str} », "
        f"annonce du programme pour « {config.title} » ;"
        f"\n- un segment flash des {config.num_headlines} titres (kind \"headlines\") ;"
        f"\n- {config.num_briefs} segments de brèves (kind \"brief\"), chacun d'environ "
        f"{config.max_brief_chars} caractères max, reprenant le titre puis le résumé "
        f"reformulé avec une transition naturelle ;"
        "\n- un segment de clôture (kind \"outro\") : prise de congé et rendez-vous à demain."
    ) if config.num_briefs > 0 else (
        f"- un segment intro (kind \"intro\") ;\n- un segment flash des {config.num_headlines} "
        "titres (kind \"headlines\") ;\n- un segment de clôture (kind \"outro\")."
    )

    return f"""Rédige le briefing podcast du {date_str} à partir des articles ci-dessous.

Structure attendue :
{briefs}

Réponds STRICTEMENT en JSON, sans texte autour, au format :
{{"segments": [{{"kind": "intro", "text": "..."}}, {{"kind": "headlines", "text": "..."}}, {{"kind": "brief", "text": "..."}}, {{"kind": "outro", "text": "..."}}]}}

Articles :
{articles}"""


def parse_segments(config: Config, content: str) -> list[Segment] | None:
    """Extrait les segments du JSON renvoyé par le modèle (fences tolérées).

    Retourne None si la réponse est inutilisable (le pipeline retombera
    sur le script déterministe).
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Certains modèles encadrent le JSON de bavardage : on isole la 1re accolade
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    raw_segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(raw_segments, list):
        return None

    segments: list[Segment] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind", "")
        text = re.sub(r"\s+", " ", str(raw.get("text", ""))).strip()
        if kind not in KIND_RATES or not text:
            continue
        rate = getattr(config, KIND_RATES[kind])
        segments.append(Segment(kind=kind, text=text, rate=rate))

    # Validation minimale : au moins intro + outro et un texte substantiel
    kinds = {segment.kind for segment in segments}
    if not {"intro", "outro"} <= kinds or sum(len(s.text) for s in segments) < 100:
        return None
    return segments


async def ai_script(
    config: Config,
    items: list[FeedItem],
    *,
    now: datetime | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[Segment] | None:
    """Demande au modèle la rédaction du briefing. None = indisponible/invalidé."""
    now = now or datetime.now(tz=PARIS)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=90)
    try:
        response = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {load_api_key(config)}",
                # En-têtes recommandés par OpenRouter pour l'attribution de l'app
                "HTTP-Referer": "https://github.com/myop-local/myop",
                "X-Title": "MYOP - My Own Podcast",
            },
            json={
                "model": config.ai.model,
                "temperature": 0.6,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(config, items, now)},
                ],
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    finally:
        if own_client:
            await client.aclose()

    return parse_segments(config, content)
