"""Tests de la configuration (round-trip YAML)."""

from app.config import Config, load_config, save_config


def test_round_trip_yaml(tmp_path):
    config = Config(title="Mon Podcast", num_briefs=3)
    path = tmp_path / "config.yaml"
    save_config(config, path)

    loaded = load_config(path)
    assert loaded == config
    assert loaded.title == "Mon Podcast"
    assert loaded.num_briefs == 3


def test_load_missing_file_returns_defaults(tmp_path):
    config = load_config(tmp_path / "absent.yaml")
    assert config.title == Config().title
    assert config.feed_url is None


def test_feed_url_uses_pages_base():
    config = Config.model_validate(
        {"github": {"pages_base": "https://me.github.io/myop/", "repo": "me/myop"}}
    )
    assert config.feed_url == "https://me.github.io/myop/podcast.xml"


def test_yaml_keeps_unicode_and_order(tmp_path):
    config = Config(title="Briefing de Renaud ☕", delivery_hour="08:15")
    path = tmp_path / "config.yaml"
    save_config(config, path)
    content = path.read_text(encoding="utf-8")
    assert "Briefing de Renaud ☕" in content
    assert content.index("title:") < content.index("delivery_hour:")  # ordre lisible conservé
