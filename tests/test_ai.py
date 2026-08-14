"""Tests du module IA : parsing des réponses, appel OpenRouter simulé, repli."""

import json
from datetime import datetime

import httpx
import pytest

from app.ai import ai_script, build_user_prompt, parse_segments
from app.config import Config
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


def test_parse_segments_plain_json(ai_config):
    segments = parse_segments(ai_config, json.dumps(AI_RESPONSE))
    assert segments is not None
    assert [s.kind for s in segments] == ["intro", "headlines", "brief", "outro"]
    # Débits repris de la config, pas du modèle
    assert segments[0].rate == ai_config.intro_rate
    assert segments[2].rate == ai_config.brief_rate


def test_parse_segments_with_markdown_fences(ai_config):
    fenced = f"```json\n{json.dumps(AI_RESPONSE)}\n```"
    assert parse_segments(ai_config, fenced) is not None


def test_parse_segments_with_chatter_around_json(ai_config):
    chatty = f"Voici le JSON demandé :\n{json.dumps(AI_RESPONSE)}\nBonne journée !"
    segments = parse_segments(ai_config, chatty)
    assert segments is not None and len(segments) == 4


def test_parse_segments_rejects_garbage(ai_config):
    assert parse_segments(ai_config, "désolé, je ne peux pas") is None
    assert parse_segments(ai_config, '{"segments": []}') is None
    assert parse_segments(ai_config, '{"segments": [{"kind": "intro", "text": "trop court"}]}') is None


def test_build_user_prompt_contains_articles_and_format(ai_config, now):
    ai_config.num_headlines = 2
    items = [make_item("Actu un", "Résumé un."), make_item("Actu deux", "Résumé deux.")]
    prompt = build_user_prompt(ai_config, items, now)
    assert "vendredi 14 août" in prompt
    assert "Actu un" in prompt and "Source : Test" in prompt
    assert '"segments"' in prompt  # format JSON imposé


async def test_ai_script_calls_openrouter(ai_config, now, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(AI_RESPONSE)}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        segments = await ai_script(ai_config, [make_item("Actu")], now=now, client=client)

    assert segments is not None
    assert captured["auth"] == "Bearer test-key"
    assert captured["payload"]["model"] == "google/gemini-3.6-flash"
    assert captured["payload"]["messages"][0]["role"] == "system"


async def test_ai_script_returns_none_on_http_error(ai_config, now):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "quota"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await ai_script(ai_config, [make_item("Actu")], now=now, client=client)


async def test_generate_falls_back_when_ai_fails(tmp_path, monkeypatch):
    """Pipeline : IA en échec → avertissement + script déterministe utilisé."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from app import generate
    from app.config import Source as SourceModel
    from app.sources import FetchResult
    from tests.test_generate import _fake_synthesize

    async def _fake_fetch(config, *, now=None, seen=None, client=None):
        return FetchResult(selected=[make_item("Actu IA", "Résumé.")], all_keys=["k"])

    async def _failing_ai(config, items, *, now=None, client=None):
        raise httpx.ConnectError("pas de réseau")

    monkeypatch.setattr(generate, "fetch_items", _fake_fetch)
    monkeypatch.setattr("app.ai.ai_script", _failing_ai)
    monkeypatch.setattr(generate, "synthesize", _fake_synthesize)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    config = Config(
        ai={"enabled": True},
        sources=[SourceModel(name="T", url="https://t.example/rss")],
    )
    result = await generate.generate_episode(
        config, tmp_path, now=dt(2026, 8, 14, 7, 30, tzinfo=ZoneInfo("Europe/Paris"))
    )
    assert result.ok
    assert not result.ai_used
    assert any("IA en échec" in w for w in result.warnings)
