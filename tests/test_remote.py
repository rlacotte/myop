"""Tests du mode distant : dashboard hébergé sans disque (Vercel).

Rien n'y touche le réseau : les appels GitHub sont simulés.
"""

import json

import httpx
import pytest

from app import remote


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("VERCEL", "MYOP_REMOTE", "MYOP_REPO", "MYOP_GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_remote_mode_is_off_by_default():
    assert remote.is_remote() is False


def test_vercel_switches_the_mode_on(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert remote.is_remote() is True


def test_writing_requires_both_repo_and_token(monkeypatch):
    monkeypatch.setenv("MYOP_REPO", "moi/myop")
    assert remote.can_write() is False  # dépôt sans jeton : lecture seule

    monkeypatch.setenv("MYOP_GITHUB_TOKEN", "jeton")
    assert remote.can_write() is True


def test_write_refused_without_token(monkeypatch):
    """Sans jeton, on ne tente même pas l'appel : pas d'échec silencieux."""
    monkeypatch.setenv("MYOP_REPO", "moi/myop")
    monkeypatch.setattr(httpx, "put", lambda *a, **k: pytest.fail("aucun appel attendu"))

    assert remote.write_file("config.yaml", "x", "message") is False


def test_read_file_uses_raw_first(monkeypatch):
    monkeypatch.setenv("MYOP_REPO", "moi/myop")
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        return httpx.Response(200, text="language: fr-FR\n")

    monkeypatch.setattr(httpx, "get", fake_get)

    assert remote.read_file("config.yaml") == "language: fr-FR\n"
    assert seen["url"] == "https://raw.githubusercontent.com/moi/myop/main/config.yaml"


def test_write_file_sends_base64_and_branch(monkeypatch):
    monkeypatch.setenv("MYOP_REPO", "moi/myop")
    monkeypatch.setenv("MYOP_GITHUB_TOKEN", "jeton")
    monkeypatch.setattr(remote, "_sha", lambda path, branch: "abc123")
    captured = {}

    def fake_put(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["auth"] = kwargs["headers"]["Authorization"]
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "put", fake_put)

    assert remote.write_file("reading.json", "[]", "maj", branch="gh-pages") is True
    import base64

    assert base64.b64decode(captured["json"]["content"]).decode() == "[]"
    assert captured["json"]["branch"] == "gh-pages"
    assert captured["json"]["sha"] == "abc123"  # remplacement, pas création
    assert captured["auth"] == "Bearer jeton"


def test_dispatch_workflow(monkeypatch):
    monkeypatch.setenv("MYOP_REPO", "moi/myop")
    monkeypatch.setenv("MYOP_GITHUB_TOKEN", "jeton")
    monkeypatch.setattr(httpx, "post", lambda url, **k: httpx.Response(204))

    assert remote.dispatch_workflow() is True


def test_dispatch_workflow_reports_failure(monkeypatch):
    monkeypatch.setenv("MYOP_REPO", "moi/myop")
    monkeypatch.setenv("MYOP_GITHUB_TOKEN", "jeton")
    monkeypatch.setattr(httpx, "post", lambda url, **k: httpx.Response(403))

    assert remote.dispatch_workflow() is False


# ------------------------------------------------- épisodes lus dans le flux --

FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Le Matin</title>
  <item>
    <title>Le Matin — 15 août</title>
    <description>Grève des trains • Budget</description>
    <pubDate>Sat, 15 Aug 2026 07:30:00 +0200</pubDate>
    <enclosure url="https://me.github.io/myop/episodes/matin/2026-08-15.mp3"
               length="2240000" type="audio/mpeg"/>
    <itunes:duration xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">6:12</itunes:duration>
  </item>
</channel></rss>"""


def test_episodes_read_from_the_public_feed(monkeypatch):
    """Sans disque, la liste des épisodes vient du flux déjà publié."""
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **k: httpx.Response(
            200, content=FEED.encode(), request=httpx.Request("GET", url)
        ),
    )

    episodes = remote.episodes_from_feed("https://me.github.io/myop/podcast.xml")

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode["id"] == "2026-08-15"
    assert episode["title"] == "Le Matin — 15 août"
    assert episode["size"] == 2240000
    assert episode["duration"] == 372  # « 6:12 » converti en secondes
    assert episode["audio"].endswith("2026-08-15.mp3")


def test_episodes_survive_an_unreachable_feed(monkeypatch):
    def boom(url, **kwargs):
        raise httpx.ConnectError("pas de réseau")

    monkeypatch.setattr(httpx, "get", boom)
    assert remote.episodes_from_feed("https://me.github.io/myop/podcast.xml") == []


@pytest.mark.parametrize(
    "value,expected", [("6:12", 372), ("1:02:03", 3723), ("372", 372), ("", 0), ("abc", 0)]
)
def test_duration_parsing(value, expected):
    assert remote._seconds(value) == expected


def test_hydrate_config_writes_the_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(remote, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(remote, "CONFIG_CACHE", tmp_path / "config.yaml")
    monkeypatch.setattr(remote, "read_file", lambda path, branch="main": "author: Moi\n")

    path = remote.hydrate_config()

    assert path and json.dumps(path.read_text(encoding="utf-8")) == json.dumps("author: Moi\n")


def test_hydrate_config_without_repo(monkeypatch):
    monkeypatch.setattr(remote, "read_file", lambda path, branch="main": None)
    assert remote.hydrate_config() is None
