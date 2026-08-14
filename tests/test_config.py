"""Tests de la configuration v2 (shows, migration, YAML)."""

import yaml

from app.config import Config, Show, load_config, save_config


def test_round_trip_yaml(tmp_path):
    config = Config(shows=[Show(title="Mon Podcast", num_briefs=3)])
    path = tmp_path / "config.yaml"
    save_config(config, path)

    loaded = load_config(path)
    assert loaded == config
    assert loaded.show().title == "Mon Podcast"
    assert loaded.show().num_briefs == 3


def test_load_missing_file_returns_defaults(tmp_path):
    config = load_config(tmp_path / "absent.yaml")
    assert config.show().title == Show().title
    assert config.feed_url() is None


def test_feed_url_first_show_uses_canonical_name(config):
    first = config.show()  # seul show → podcast.xml
    assert config.feed_url(first) == "https://me.github.io/myop/podcast.xml"

    config.shows.append(Show(id="soir", title="Le Soir"))
    assert config.feed_url(config.show("soir")) == "https://me.github.io/myop/podcast-soir.xml"
    assert config.feed_url(first) == "https://me.github.io/myop/podcast.xml"


def test_show_selector_fallback_and_errors():
    config = Config(shows=[Show(id="a", enabled=False), Show(id="b")])
    assert config.show().id == "b"  # ignore les émissions en pause
    assert config.show("a").id == "a"
    import pytest

    with pytest.raises(KeyError):
        config.show("inconnu")


def test_show_id_slug_validation():
    import pytest
    from pydantic import ValidationError

    assert Show(id="  Mon Show ").id == "mon-show"
    with pytest.raises(ValidationError):
        Show(id="!invalide!")


def test_migration_v1_to_shows(tmp_path):
    v1 = {
        "title": "Ancien Podcast",
        "voice": "fr-FR-HenriNeural",
        "num_briefs": 2,
        "sources": [{"name": "X", "url": "https://x.example/rss"}],
        "github": {"repo": "a/b", "pages_base": None},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(v1, allow_unicode=True), encoding="utf-8")

    migrated = load_config(path)
    assert len(migrated.shows) == 1
    show = migrated.show()
    assert show.title == "Ancien Podcast"
    assert show.voice == "fr-FR-HenriNeural"
    assert show.num_briefs == 2
    assert len(show.sources) == 1
    assert migrated.github.repo == "a/b"
