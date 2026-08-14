"""Tests dashboard v2 : shows, bibliothèque, OPML, lecture, feedback, script."""

import pytest
from fastapi.testclient import TestClient

from app.config import Config, Show, Source, load_config, save_config
from app.library import LIBRARY, library_urls


def test_library_structure_is_sound():
    assert len(LIBRARY) >= 12
    all_urls = []
    for category, feeds in LIBRARY.items():
        assert feeds, f"catégorie vide : {category}"
        for feed in feeds:
            assert feed["name"] and feed["url"].startswith("https://")
            all_urls.append(feed["url"])
    assert len(all_urls) == len(set(all_urls)), "URL en double dans la bibliothèque"
    assert any("International" in cat for cat in LIBRARY)  # catégorie traduite par l'IA


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirige config.yaml ET dist/ vers des répertoires temporaires."""
    path = tmp_path / "config.yaml"
    save_config(
        Config(shows=[Show(id="matin", sources=[Source(name="Perso", url="https://perso.example/rss")])]),
        path,
    )
    monkeypatch.setattr("app.config.CONFIG_PATH", path)
    # le dashboard écrit dans DIST_DIR (module generate) — redirection
    monkeypatch.setattr("app.generate.DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr("app.dashboard.DIST_DIR", tmp_path / "dist")
    (tmp_path / "dist" / "episodes").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def client(isolated_config):
    from app.dashboard import app

    with TestClient(app) as test_client:
        yield test_client


def test_state_lists_shows(client):
    data = client.get("/api/state").json()
    assert data["current_show"] == "matin"
    assert data["shows"][0]["id"] == "matin"


def test_library_endpoint_marks_active_feeds(client):
    data = client.get("/api/library").json()
    categories = {c["category"]: c for c in data["categories"]}
    numerama = next(
        f for f in categories["Tech & numérique"]["feeds"] if "numerama" in f["url"]
    )
    assert numerama["active"] is False
    assert data["custom"] == [{"index": 0, "name": "Perso", "url": "https://perso.example/rss"}]


def test_toggle_library_source(client):
    url = "https://www.numerama.com/feed/"
    response = client.post("/api/library/toggle", json={"url": url, "enabled": True})
    assert response.status_code == 200
    assert any(s.url == url for s in load_config().show().sources)

    response = client.post("/api/library/toggle", json={"url": url, "enabled": False})
    assert response.status_code == 200
    assert not any(s.url == url for s in load_config().show().sources)

    assert client.post("/api/library/toggle", json={"url": "https://x.example/x", "enabled": True}).status_code == 404


def test_toggle_whole_category(client):
    crypto_urls = {f["url"] for f in LIBRARY["Crypto"]}
    response = client.post("/api/library/category", json={"category": "Crypto", "enabled": True})
    assert response.status_code == 200
    assert crypto_urls <= {s.url for s in load_config().show().sources}

    response = client.post("/api/library/category", json={"category": "Crypto", "enabled": False})
    assert response.status_code == 200
    assert not crypto_urls & {s.url for s in load_config().show().sources}


def test_create_and_delete_show(client):
    response = client.post("/api/shows", json={"title": "Briefing Soir", "delivery_hour": "18:00"})
    assert response.status_code == 200
    new_id = response.json()["id"]
    assert any(s.id == new_id for s in load_config().shows)

    # Les sources du nouveau show partent de celles du show courant
    assert load_config().show(new_id).sources

    assert client.delete(f"/api/shows/{new_id}").status_code == 200
    assert not any(s.id == new_id for s in load_config().shows)
    assert client.delete("/api/shows/matin").status_code == 400  # dernière émission


def test_settings_update_show_and_global(client):
    response = client.put(
        "/api/settings",
        json={"title": "Nouveau Titre", "weather_city": "Lyon", "ai_persona": "humoriste"},
    )
    assert response.status_code == 200
    config = load_config()
    assert config.show().title == "Nouveau Titre"
    assert config.show().weather_city == "Lyon"
    assert config.ai.persona == "humoriste"

    # Validation de l'heure
    assert client.put("/api/settings", json={"delivery_hour": "99:99"}).status_code == 400


def test_opml_roundtrip(client):
    # Export
    export = client.get("/api/opml")
    assert export.status_code == 200
    assert "perso.example" in export.text and "<outline" in export.text

    # Import
    opml = """<?xml version="1.0"?><opml><body>
      <outline type="rss" text="Flux importé" xmlUrl="https://importe.example/rss"/>
    </body></opml>"""
    response = client.post("/api/opml", json={"content": opml})
    assert response.status_code == 200
    assert response.json()["added"] == 1
    assert any(s.url == "https://importe.example/rss" for s in load_config().show().sources)

    assert client.post("/api/opml", json={"content": "pas du xml"}).status_code == 422


def test_reading_queue_crud(client):
    assert client.get("/api/reading").json() == []

    # L'ajout réel exige le réseau : on passe par le module directement
    from app import reading as reading_mod
    from app.generate import DIST_DIR

    save = reading_mod.save_queue(DIST_DIR, [
        reading_mod.ReadingItem(url="https://a.example/1", title="Article A", text="x" * 100),
        reading_mod.ReadingItem(url="https://a.example/2", title="Article B", text="y" * 100),
    ])
    data = client.get("/api/reading").json()
    assert [item["title"] for item in data] == ["Article A", "Article B"]

    assert client.delete("/api/reading/0").status_code == 200
    assert [item["title"] for item in client.get("/api/reading").json()] == ["Article B"]
    assert client.delete("/api/reading/9").status_code == 404


def test_feedback_vote_and_reset(client):
    response = client.post(
        "/api/feedback",
        json={"source": "Le Monde", "title": "Une actu intéressante", "good": True},
    )
    assert response.status_code == 200
    assert response.json()["source_score"] == 1

    data = client.get("/api/feedback").json()
    assert data["source_scores"]["Le Monde"] == 1

    assert client.delete("/api/feedback").status_code == 200
    assert client.get("/api/feedback").json()["source_scores"] == {}


def test_generate_validates_date(client):
    response = client.post("/api/generate", json={"date": "pas-une-date"})
    assert response.status_code == 400
    response = client.post("/api/generate", json={"show_id": "inconnu"})
    assert response.status_code == 404


def test_script_render_validates_segments(client):
    response = client.post("/api/script/render", json={"segments": []})
    assert response.status_code == 400
