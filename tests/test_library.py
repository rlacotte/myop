"""Tests de la bibliothèque de sources et de l'API du dashboard."""

import pytest
from fastapi.testclient import TestClient

from app.config import Config, Source, load_config, save_config
from app.library import LIBRARY, library_urls


def test_library_structure_is_sound():
    """Chaque catégorie est non vide, les flux sont uniques et complets."""
    assert len(LIBRARY) >= 10
    all_urls = []
    for category, feeds in LIBRARY.items():
        assert feeds, f"catégorie vide : {category}"
        for feed in feeds:
            assert feed["name"] and feed["url"].startswith("https://")
            all_urls.append(feed["url"])
    assert len(all_urls) == len(set(all_urls)), "URL en double dans la bibliothèque"
    assert len(library_urls()) == len(all_urls)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirige config.yaml vers un fichier temporaire (pas d'effet de bord)."""
    path = tmp_path / "config.yaml"
    save_config(Config(sources=[Source(name="Perso", url="https://perso.example/rss")]), path)
    monkeypatch.setattr("app.config.CONFIG_PATH", path)
    return path


@pytest.fixture
def client(isolated_config):
    from app.dashboard import app

    with TestClient(app) as test_client:
        yield test_client


def test_library_endpoint_marks_active_feeds(client):
    response = client.get("/api/library")
    assert response.status_code == 200
    data = response.json()

    categories = {c["category"]: c for c in data["categories"]}
    assert "Tech & numérique" in categories
    numerama = next(
        f for f in categories["Tech & numérique"]["feeds"] if "numerama" in f["url"]
    )
    assert numerama["active"] is False

    # Le flux perso (hors bibliothèque) apparaît dans la section dédiée
    assert data["custom"] == [{"index": 0, "name": "Perso", "url": "https://perso.example/rss"}]
    assert data["active_count"] == 1


def test_toggle_library_source_adds_and_removes(client):
    # Activation
    response = client.post(
        "/api/library/toggle",
        json={"url": "https://www.numerama.com/feed/", "enabled": True},
    )
    assert response.status_code == 200
    config = load_config()
    assert any(s.url == "https://www.numerama.com/feed/" for s in config.sources)

    # Désactivation
    response = client.post(
        "/api/library/toggle",
        json={"url": "https://www.numerama.com/feed/", "enabled": False},
    )
    assert response.status_code == 200
    assert not any(
        s.url == "https://www.numerama.com/feed/" for s in load_config().sources
    )

    # Flux inconnu → 404
    assert client.post("/api/library/toggle", json={"url": "https://x.example/x", "enabled": True}).status_code == 404


def test_toggle_whole_category(client):
    response = client.post(
        "/api/library/category",
        json={"category": "Crypto", "enabled": True},
    )
    assert response.status_code == 200
    config = load_config()
    crypto_urls = {f["url"] for f in LIBRARY["Crypto"]}
    assert crypto_urls <= {s.url for s in config.sources}

    response = client.post(
        "/api/library/category",
        json={"category": "Crypto", "enabled": False},
    )
    assert response.status_code == 200
    assert not crypto_urls & {s.url for s in load_config().sources}

    assert (
        client.post("/api/library/category", json={"category": "N'existe pas", "enabled": True}).status_code
        == 404
    )


def test_custom_source_still_addable(client):
    response = client.post(
        "/api/sources",
        json={"name": "Mon flux", "url": "https://flux.example/rss"},
    )
    assert response.status_code == 200
    data = client.get("/api/library").json()
    names = [c["name"] for c in data["custom"]]
    assert "Mon flux" in names
