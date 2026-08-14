"""Rédaction du script assistée par IA (optionnelle), via OpenRouter.

Le modèle réécrit les articles collectés en briefing radio naturel, avec :
- un persona éditable (config.ai.persona) ou une consigne système libre
- le contexte du jour (météo, éphéméride, liste de lecture)
- un mode dialogue à deux voix quand show.voice_co est défini
- la traduction des sources en langue étrangère

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

from .config import Config, Show
from .script import PARIS, Segment, format_date_fr
from .sources import FeedItem

ROOT = Path(__file__).resolve().parent.parent
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

BASE_PROMPT = (
    "Tu es {persona}. Tu rédiges des flashs d'actualité en français pour être lus "
    "à voix haute par une synthèse vocale : phrases courtes, rythme parlé, "
    "aucune URL, aucun emoji, aucun sigle imprononçable non développé. "
    "Tu t'appuies STRICTEMENT sur les éléments fournis : aucun fait inventé. "
    "Si un article est en langue étrangère, résume-le en français."
)

KIND_RATES = {
    "intro": "intro_rate",
    "headlines": "brief_rate",
    "meteo": "intro_rate",
    "brief": "brief_rate",
    "reading": "brief_rate",
    "outro": "intro_rate",
}


def load_api_key(config: Config) -> str | None:
    """Clé depuis le fichier local (non versionné) ou la variable d'environnement."""
    key_file = ROOT / config.ai.key_file
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    return os.environ.get("OPENROUTER_API_KEY") or None


def system_prompt(config: Config) -> str:
    """Consigne système : prompt libre si fourni, sinon base + persona."""
    if config.ai.system_prompt:
        return config.ai.system_prompt
    return BASE_PROMPT.format(persona=config.ai.persona)


def build_user_prompt(
    show: Show,
    items: list[FeedItem],
    now: datetime,
    *,
    weather_line: str = "",
    ephemeris_line: str = "",
    reading_items: list | None = None,
) -> str:
    """Consigne détaillée + articles sourcés + contexte du jour, en JSON strict."""
    date_str = format_date_fr(now)
    articles = "\n".join(
        f"{i}. {item.title}\n   Source : {item.source_name}\n"
        f"   Résumé : {item.summary[: show.max_brief_chars] or '(pas de résumé)'}"
        for i, item in enumerate(items[: show.num_headlines], start=1)
    )

    dialogue = show.voice_co is not None
    speaker_note = (
        ' Chaque segment porte un locuteur : "speaker": "host" ou "speaker": "co". '
        "Les deux voix se répondent naturellement, comme un duo de radio "
        "(l'host mène, le co commente une brève sur deux environ)."
        if dialogue
        else ""
    )

    sections = [
        f'- un segment intro (kind "intro") : souhait de bonjour, date « {date_str} »{", " + ephemeris_line.strip().rstrip(".") if ephemeris_line else ""}, annonce du programme pour « {show.title} » ;',
        f'- un segment flash des {show.num_headlines} titres (kind "headlines") ;',
    ]
    if weather_line:
        sections.append('- un segment météo (kind "meteo") reprenant ces données ;')
    sections.append(
        f'- {show.num_briefs} segments de brèves (kind "brief"), chacun d\'environ '
        f"{show.max_brief_chars} caractères max, reprenant le titre puis le résumé "
        "reformulé avec une transition naturelle ;"
    )
    if reading_items:
        sections.append(
            f'- {len(reading_items)} segment(s) "à lire" (kind "reading") : présente chaque '
            "article de la liste de lecture et résume-en l'essentiel ;"
        )
    sections.append(
        '- un segment de clôture (kind "outro") : prise de congé et rendez-vous à demain.'
    )

    context = ""
    if weather_line:
        context += f"\nMétéo du jour : {weather_line}\n"
    if reading_items:
        context += "\nListe de lecture (articles à faire écouter) :\n"
        for item in reading_items:
            context += f"- {item.title} — {(getattr(item, 'text', '') or '')[:1500]}\n"

    speaker_field = '"speaker": "host" | "co", ' if dialogue else ""
    return f"""Rédige le briefing podcast du {date_str} à partir des articles ci-dessous.

Structure attendue :
{chr(10).join(sections)}{speaker_note}

Réponds STRICTEMENT en JSON, sans texte autour, au format :
{{"segments": [{{"kind": "intro", {speaker_field}"text": "..."}}, {{"kind": "headlines", "text": "..."}}, {{"kind": "brief", "text": "..."}}, {{"kind": "outro", "text": "..."}}]}}
{context}
Articles :
{articles}"""


def parse_segments(show: Show, content: str) -> list[Segment] | None:
    """Extrait les segments du JSON renvoyé par le modèle (fences tolérées).

    Retourne None si la réponse est inutilisable (le pipeline retombera
    sur le script déterministe).
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Certains modèles encadrent le JSON de bavardage : on isole la 1ʳᵉ accolade
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
        rate = getattr(show, KIND_RATES[kind])
        speaker = raw.get("speaker")
        if speaker not in ("host", "co"):
            speaker = None
        elif speaker == "co" and not show.voice_co:
            speaker = None  # pas de 2ᵉ voix configurée
        segments.append(Segment(kind=kind, text=text, rate=rate, speaker=speaker))

    # Validation minimale : au moins intro + outro et un minimum de matière
    kinds = {segment.kind for segment in segments}
    if not {"intro", "outro"} <= kinds or sum(len(s.text) for s in segments) < 20:
        return None
    return segments


async def ai_script(
    show: Show,
    config: Config,
    items: list[FeedItem],
    *,
    now: datetime | None = None,
    weather_line: str = "",
    ephemeris_line: str = "",
    reading_items: list | None = None,
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
                    {"role": "system", "content": system_prompt(config)},
                    {
                        "role": "user",
                        "content": build_user_prompt(
                            show,
                            items,
                            now,
                            weather_line=weather_line,
                            ephemeris_line=ephemeris_line,
                            reading_items=reading_items,
                        ),
                    },
                ],
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    finally:
        if own_client:
            await client.aclose()

    return parse_segments(show, content)
