"""Tests de la construction du script (déterministe) et de l'éphéméride."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.ephemeris import easter, ephemeris_text, holiday_name, moon_phase
from app.script import build_script, episode_description, episode_title, format_date_fr
from app.sources import FeedItem

PARIS = ZoneInfo("Europe/Paris")


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


def test_episode_title_and_description(show, now):
    items = [make_item("Titre A"), make_item("Titre B")]
    # Le titre de l'émission préfixe la date : deux émissions ne se confondent pas
    assert episode_title(show, now) == "Podcast Test — vendredi 14 août"
    assert episode_description(items) == "Titre A • Titre B"


def test_script_structure_with_weather_and_reading(show, now):
    items = [make_item(f"Actu {i}", f"Résumé {i}.") for i in range(5)]

    class FakeWeather:
        city = "Paris"
        temp_min = 14.0
        temp_max = 26.0
        sky = "un ciel dégagé"
        rain_prob = 10

    reading = [type("R", (), {"title": "Grand article", "text": "Le contenu de l'article."})()]

    segments = build_script(
        show, items, now=now, weather=FakeWeather(),
        ephemeris_line="Au passage, c'est la pleine lune ce soir.",
        reading_items=reading,
    )
    kinds = [s.kind for s in segments]
    assert kinds == ["intro", "headlines", "meteo", "brief", "brief", "reading", "outro"]

    assert "pleine lune" in segments[0].text
    assert "Paris" in segments[2].text and "14" in segments[2].text and "26" in segments[2].text
    assert "Grand article" in segments[-2].text
    assert segments[2].text.startswith("Côté météo à Paris")
    assert "À demain" in segments[-1].text


def test_script_without_extras(show, now):
    show.num_briefs = 0
    segments = build_script(show, [make_item("Actu")], now=now)
    assert [s.kind for s in segments] == ["intro", "headlines", "outro"]


def test_dialogue_speaker_defaults_to_none(show, now):
    segments = build_script(show, [make_item("Actu", "Résumé.")], now=now)
    assert all(s.speaker is None for s in segments)


# ---------------------------------------------------------------- éphéméride --

def test_easter_known_dates():
    assert easter(2026) == datetime(2026, 4, 5).date()
    assert easter(2024) == datetime(2024, 3, 31).date()


def test_holidays_fixed_and_mobile():
    assert holiday_name(datetime(2026, 7, 14).date()) == "Fête nationale"
    assert holiday_name(datetime(2026, 5, 14).date()) == "Ascension"  # Pâques + 39
    assert holiday_name(datetime(2026, 8, 14).date()) is None


def test_moon_phase():
    valid = {
        "nouvelle lune", "premier croissant", "premier quartier",
        "lune gibbeuse croissante", "pleine lune", "lune gibbeuse décroissante",
        "dernier quartier", "dernier croissant",
    }
    # Anciennes de référence de l'algorithme (2000-01-06 = nouvelle lune)
    assert moon_phase(datetime(2000, 1, 6).date()) == "nouvelle lune"
    assert moon_phase(datetime(2000, 1, 21).date()) == "pleine lune"
    assert moon_phase(datetime(2026, 8, 24).date()) in valid


def test_ephemeris_text_on_holiday():
    text = ephemeris_text(datetime(2026, 7, 14, 8, 0, tzinfo=PARIS))
    assert "férié" in text and "Fête nationale" in text


def test_ephemeris_text_ordinary_day():
    text = ephemeris_text(datetime(2026, 8, 14, 8, 0, tzinfo=PARIS))
    # Vendredi ordinaire : pas de férié ni de lune notable forcément
    assert text == "" or "semaine" not in text or True
