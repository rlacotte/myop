"""Tests de l'aiguillage par émission dans le dashboard.

Le front envoie « ?show=<id> » : chaque endpoint doit viser cette émission
et non retomber silencieusement sur la première (régression v2).
"""

import pytest
from fastapi.testclient import TestClient

from app.config import Config, Show, Source, save_config


@pytest.fixture
def two_shows(tmp_path, monkeypatch):
    """Deux émissions, chacune avec sa propre source, config et dist isolées."""
    path = tmp_path / "config.yaml"
    save_config(
        Config(
            shows=[
                Show(id="matin", title="Le Matin",
                     sources=[Source(name="Source Matin", url="https://matin.example/rss")]),
                Show(id="soir", title="Le Soir", delivery_hour="18:00",
                     sources=[Source(name="Source Soir", url="https://soir.example/rss")]),
            ],
            github={"pages_base": "https://me.github.io/myop/"},
        ),
        path,
    )
    monkeypatch.setattr("app.config.CONFIG_PATH", path)
    monkeypatch.setattr("app.generate.DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr("app.dashboard.DIST_DIR", tmp_path / "dist")
    (tmp_path / "dist" / "episodes").mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def client(two_shows):
    from app.dashboard import app

    return TestClient(app)


def test_sources_follow_the_requested_show(client):
    assert client.get("/api/sources?show=soir").json()[0]["name"] == "Source Soir"
    assert client.get("/api/sources?show=matin").json()[0]["name"] == "Source Matin"
    # Sans paramètre : première émission activée
    assert client.get("/api/sources").json()[0]["name"] == "Source Matin"


def test_library_and_opml_follow_the_requested_show(client):
    custom = client.get("/api/library?show=soir").json()["custom"]
    assert [c["name"] for c in custom] == ["Source Soir"]
    assert "soir.example" in client.get("/api/opml?show=soir").text


def test_delete_source_targets_the_requested_show(client, two_shows):
    """Le bug : supprimer la source 0 de « soir » vidait « matin »."""
    from app.config import load_config

    assert client.delete("/api/sources/0?show=soir").status_code == 200
    config = load_config(two_shows)
    assert [s.name for s in config.show("matin").sources] == ["Source Matin"]
    assert config.show("soir").sources == []


def test_qr_code_encodes_the_show_feed(client):
    assert client.get("/api/qr.png?show=soir").headers["content-type"] == "image/png"


def test_unknown_show_is_rejected(client):
    assert client.get("/api/sources?show=inconnue").status_code == 404


def test_generation_status_is_keyed_by_show(client, monkeypatch):
    """Statut lisible par le front, y compris pour une émission non-première."""
    import app.dashboard as dashboard

    dashboard._jobs.clear()
    dashboard._jobs["generate:soir"] = {"running": True, "log": ["en cours"], "result": None}

    assert client.get("/api/generate/status?show=soir").json()["running"] is True
    assert client.get("/api/generate/status?show=matin").json()["running"] is False
    dashboard._jobs.clear()


def test_script_render_reports_under_the_show_key(client, monkeypatch):
    """Un script édité pour « soir » doit publier son état sous « generate:soir ».

    Auparavant le job partait sous « generate:default » : la barre de
    progression du dashboard restait bloquée indéfiniment.
    """
    import app.dashboard as dashboard

    captured = {}

    async def _fake_generate(config, show, dist_dir=None, *, now=None, ignore_seen=False, draft=None):
        from app.generate import GenerationResult

        captured["show_id"] = show.id
        captured["title"] = draft.title
        return GenerationResult(ok=True, show_id=show.id, episode_id="2026-08-15")

    monkeypatch.setattr(dashboard, "generate_episode", _fake_generate)
    dashboard._jobs.clear()

    response = client.post(
        "/api/script/render",
        json={"show_id": "soir", "segments": [{"kind": "intro", "text": "Bonsoir."}],
              "titles": ["Un titre"]},
    )
    assert response.status_code == 200
    assert "generate:soir" in dashboard._jobs

    # La tâche de fond s'exécute lors de la requête de statut suivante
    status = client.get("/api/generate/status?show=soir").json()
    assert status["result"]["ok"] is True
    assert captured["show_id"] == "soir"
    # Le titre suit l'émission : plus de « Briefing du … » en dur
    assert captured["title"].startswith("Le Soir")
    dashboard._jobs.clear()


def test_retention_setting_is_saved_globally(client, two_shows):
    from app.config import load_config

    assert client.put("/api/settings", json={"show_id": "soir", "keep_episodes": 10}).status_code == 200
    assert load_config(two_shows).publishing.keep_episodes == 10

    # Bornes du modèle respectées
    assert client.put("/api/settings", json={"keep_episodes": -1}).status_code == 422


def test_tone_examples_round_trip_through_the_form(client, two_shows):
    """Le formulaire envoie un bloc de texte ; la config stocke une liste."""
    from app.config import load_config

    blob = "Premier extrait, celui du matin.\n---\nDeuxième extrait, plus sec."
    assert client.put("/api/settings", json={"ai_tone_examples": blob}).status_code == 200
    assert load_config(two_shows).ai.tone_examples == [
        "Premier extrait, celui du matin.",
        "Deuxième extrait, plus sec.",
    ]

    # Vider le champ efface les exemples
    assert client.put("/api/settings", json={"ai_tone_examples": ""}).status_code == 200
    assert load_config(two_shows).ai.tone_examples == []


def test_settings_page_renders_current_tone_examples(client, two_shows):
    client.put("/api/settings", json={"ai_tone_examples": "Un extrait\n---\nDeux"})
    page = client.get("/").text
    assert "Un extrait\n---\nDeux" in page


def test_draft_survives_a_reload_and_is_per_show(client, tmp_path):
    """Le brouillon est stocké côté serveur : fermer l'onglet ne perd rien."""
    assert client.get("/api/script/draft?show=soir").json()["draft"] is None

    saved = client.put(
        "/api/script/draft",
        json={"show_id": "soir", "title": "Édition du soir",
              "segments": [{"kind": "intro", "text": "Bonsoir."},
                           {"kind": "brief", "text": "Une brève."}]},
    )
    assert saved.json() == {"ok": True, "segments": 2}

    draft = client.get("/api/script/draft?show=soir").json()["draft"]
    assert draft["title"] == "Édition du soir"
    assert [s["text"] for s in draft["segments"]] == ["Bonsoir.", "Une brève."]
    # Chaque émission a le sien
    assert client.get("/api/script/draft?show=matin").json()["draft"] is None

    assert client.delete("/api/script/draft?show=soir").status_code == 200
    assert client.get("/api/script/draft?show=soir").json()["draft"] is None


def test_draft_save_keeps_the_collection_context(client):
    """Réordonner des segments ne doit pas perdre l'historisation ni la file de lecture."""
    import app.dashboard as dashboard

    dashboard._save_draft(
        dashboard.load_config().show("soir"),
        {"segments": [{"kind": "intro", "text": "Bonsoir."}], "items_keys": ["https://ex/1"],
         "reading_items": [{"url": "https://ex/a", "title": "A", "text": "…"}], "titles": ["T"]},
    )
    client.put("/api/script/draft",
               json={"show_id": "soir", "segments": [{"kind": "outro", "text": "À demain."}]})

    draft = client.get("/api/script/draft?show=soir").json()["draft"]
    assert draft["items_keys"] == ["https://ex/1"]
    assert draft["reading_items"][0]["url"] == "https://ex/a"
    assert draft["segments"][0]["kind"] == "outro"


def test_render_honours_an_edited_title_and_empties_the_reading_queue(client, monkeypatch):
    import app.dashboard as dashboard

    captured = {}

    async def _fake_generate(config, show, dist_dir=None, *, now=None, ignore_seen=False, draft=None):
        from app.generate import GenerationResult

        captured["title"] = draft.title
        captured["reading"] = draft.reading_items
        return GenerationResult(ok=True, show_id=show.id, episode_id="2026-08-15")

    monkeypatch.setattr(dashboard, "generate_episode", _fake_generate)
    dashboard._jobs.clear()

    client.post(
        "/api/script/render",
        json={"show_id": "soir", "title": "Spéciale élections",
              "segments": [{"kind": "intro", "text": "Bonsoir."}],
              "reading_items": [{"url": "https://ex/a", "title": "A", "text": "Contenu"}]},
    )
    client.get("/api/generate/status?show=soir")  # laisse tourner la tâche de fond

    assert captured["title"] == "Spéciale élections"
    # Sans cela, les articles lus restaient en file et repassaient le lendemain
    assert [item.url for item in captured["reading"]] == ["https://ex/a"]
    dashboard._jobs.clear()


def test_script_render_refuses_empty_script(client):
    response = client.post("/api/script/render", json={"show_id": "soir", "segments": []})
    assert response.status_code == 400
