"""Tests de la rédaction du script parlé."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.script import PARIS, build_script, episode_description, episode_title, format_date_fr
from app.sources import FeedItem


def make_item(title: str, summary: str = "") -> FeedItem:
    return FeedItem(
        title=title,
        url=f"https://ex.com/{title}",
        published=None,
        summary=summary,
        source_name="Test",
        guid=f"guid-{title}",
    )


def test_format_date_fr(now):
    assert format_date_fr(now) == "vendredi 14 août"


def test_episode_title_and_description(now):
    items = [make_item("Titre A"), make_item("Titre B")]
    assert episode_title(now) == "Briefing du vendredi 14 août"
    assert episode_description(items) == "Titre A • Titre B"


def test_script_structure(config, now):
    items = [make_item(f"Actu {i}", f"Résumé {i}.") for i in range(5)]
    segments = build_script(config, items, now=now)

    kinds = [segment.kind for segment in segments]
    assert kinds == ["intro", "headlines", "brief", "brief", "outro"]

    intro = segments[0]
    assert config.title in intro.text
    assert "vendredi 14 août" in intro.text

    headlines = segments[1]
    for i in range(config.num_headlines):
        assert f"Actu {i}." in headlines.text

    # Brèves détaillées avec ordinaux féminins
    assert segments[2].text.startswith("Première brève : Actu 0. Résumé 0.")
    assert segments[3].text.startswith("Deuxième brève : Actu 1. Résumé 1.")

    assert "À demain" in segments[-1].text


def test_brief_truncated_to_max_chars(config, now):
    config.max_brief_chars = 40
    long_summary = "Une phrase courte. " + "Très longue suite. " * 10
    item = make_item("Actu longue", long_summary)
    segment = build_script(config, [item], now=now)[2]
    # Coupé avant le texte intégral, sur une fin de phrase complète
    assert len(segment.text) < len(long_summary) + 50
    assert segment.text.rstrip().endswith(".")
    assert segment.text.count("Très longue suite") == 1  # pas le texte intégral (×10)


def test_no_briefs_when_zero(config, now):
    config.num_briefs = 0
    segments = build_script(config, [make_item("Actu")], now=now)
    assert [s.kind for s in segments] == ["intro", "headlines", "outro"]
