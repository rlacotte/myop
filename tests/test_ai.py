"""Tests du module IA : prompt, parsing des réponses, appel OpenRouter simulé, repli."""

import json

import httpx
import pytest

from app.ai import ai_script, build_user_prompt, parse_segments, system_prompt
from app.config import Config, Show
from app.sources import FeedItem


def make_item(title: str, summary: str = "") -> FeedItem:
    return FeedItem(
        title=title,
        url=f"https://ex.com/{title}",
        published=None,
        summary=summary,
        source_name="Test",
        guid=f"g-{title}",
    )


@pytest.fixture
def ai_config() -> Config:
    # key_file inexistant → la clé vient de la variable d'environnement (test)
    return Config(
        ai={"enabled": True, "model": "google/gemini-3.6-flash", "key_file": ".absent-key"}
    )


AI_RESPONSE = {
    "segments": [
        {"kind": "intro", "text": "Bonjour, voici votre briefing du vendredi 14 août."},
        {"kind": "headlines", "text": "Dans les titres : Actu un, Actu deux."},
        {"kind": "brief", "text": "Première brève, l'actu un en détail."},
        {"kind": "outro", "text": "Voilà pour aujourd'hui, à demain !"},
    ]
}


def test_parse_segments_plain_json(show):
    segments = parse_segments(show, json.dumps(AI_RESPONSE))
    assert segments is not None
    assert [s.kind for s in segments] == ["intro", "headlines", "brief", "outro"]
    # Débits repris de l'émission, pas du modèle
    assert segments[0].rate == show.intro_rate
    assert segments[2].rate == show.brief_rate


def test_parse_segments_with_markdown_fences(show):
    fenced = f"```json\n{json.dumps(AI_RESPONSE)}\n```"
    assert parse_segments(show, fenced) is not None


def test_parse_segments_with_chatter_around_json(show):
    chatty = f"Voici le JSON demandé :\n{json.dumps(AI_RESPONSE)}\nBonne journée !"
    segments = parse_segments(show, chatty)
    assert segments is not None and len(segments) == 4


def test_parse_segments_rejects_garbage(show):
    assert parse_segments(show, "désolé, je ne peux pas") is None
    assert parse_segments(show, '{"segments": []}') is None
    # Intro seule, sans outro ni matière : inutilisable
    assert parse_segments(show, '{"segments": [{"kind": "intro", "text": "trop court"}]}') is None


def test_parse_segments_drops_second_voice_without_dialogue(show):
    """Un « speaker: co » sans 2ᵉ voix configurée ne doit pas router vers une voix absente."""
    response = {
        "segments": [
            {"kind": "intro", "text": "Bonjour à tous, voici les nouvelles.", "speaker": "host"},
            {"kind": "brief", "text": "La brève du jour, commentée.", "speaker": "co"},
            {"kind": "outro", "text": "C'est fini pour aujourd'hui, à demain."},
        ]
    }
    assert show.voice_co is None
    assert [s.speaker for s in parse_segments(show, json.dumps(response))] == ["host", None, None]

    show.voice_co = "fr-FR-VivienneMultilingualNeural"
    assert [s.speaker for s in parse_segments(show, json.dumps(response))] == ["host", "co", None]


def test_build_user_prompt_contains_articles_and_format(show, now):
    show.num_headlines = 2
    items = [make_item("Actu un", "Résumé un."), make_item("Actu deux", "Résumé deux.")]
    prompt = build_user_prompt(show, items, now)

    assert "vendredi 14 août" in prompt
    assert "Actu un" in prompt and "Source : Test" in prompt
    assert '"segments"' in prompt  # format JSON imposé


def test_build_user_prompt_includes_context_segments(show, now):
    prompt = build_user_prompt(
        show,
        [make_item("Actu")],
        now,
        weather_line="15 à 26 degrés, un ciel dégagé",
        ephemeris_line="C'est la Saint-Machin.",
        reading_items=[type("R", (), {"title": "Mon article", "text": "Contenu long."})()],
    )
    assert "un ciel dégagé" in prompt
    assert 'kind "meteo"' in prompt
    assert "Mon article" in prompt


def test_system_prompt_uses_persona_then_custom_override():
    config = Config(ai={"persona": "un pirate radiophonique"})
    assert "un pirate radiophonique" in system_prompt(config)

    config.ai.system_prompt = "Consigne maison."
    assert system_prompt(config) == "Consigne maison."


async def test_ai_script_calls_openrouter(show, ai_config, now, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(AI_RESPONSE)}}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        segments = await ai_script(
            show, ai_config, [make_item("Actu")], now=now, client=client
        )

    assert segments is not None
    assert captured["auth"] == "Bearer test-key"
    assert captured["payload"]["model"] == "google/gemini-3.6-flash"
    assert captured["payload"]["messages"][0]["role"] == "system"


async def test_ai_script_raises_on_http_error(show, ai_config, now, monkeypatch):
    """Le pipeline attrape l'exception et bascule sur le script déterministe."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "quota"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await ai_script(show, ai_config, [make_item("Actu")], now=now, client=client)


async def test_generate_falls_back_when_ai_fails(tmp_path, show, monkeypatch):
    """Pipeline complet : IA en échec → avertissement + script déterministe."""
    from datetime import datetime as dt

    from app import generate
    from app.script import PARIS
    from app.sources import FetchResult
    from tests.test_generate import _fake_synthesize

    async def _fake_fetch(show, *, now=None, seen=None, client=None, ranker=None):
        return FetchResult(selected=[make_item("Actu IA", "Résumé.")], all_keys=["k"])

    async def _failing_ai(*args, **kwargs):
        raise httpx.ConnectError("pas de réseau")

    monkeypatch.setattr(generate, "fetch_items", _fake_fetch)
    monkeypatch.setattr("app.ai.ai_script", _failing_ai)
    monkeypatch.setattr(generate, "synthesize", _fake_synthesize)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    config = Config(shows=[show], ai={"enabled": True, "key_file": ".absent-key"})
    result = await generate.generate_episode(
        config, show, tmp_path, now=dt(2026, 8, 14, 7, 30, tzinfo=PARIS)
    )

    assert result.ok
    assert not result.ai_used
    assert any("IA en échec" in w for w in result.warnings)
