"""Tests de la transcription : WebVTT, texte lisible, balise dans le flux."""

from app.feed import add_transcripts
from app.script import Segment
from app.transcript import build_text, build_vtt, write_transcript

SEGMENTS = [
    Segment("intro", "Bonjour, il est sept heures trente.", "-8%", speaker="host"),
    Segment("brief", "La première brève du jour.", "+4%", speaker="co"),
    Segment("outro", "À demain.", "-8%"),
]
CHAPTERS = [
    {"title": "Intro", "start_ms": 0, "end_ms": 3400},
    {"title": "Brève 1", "start_ms": 3800, "end_ms": 9000},
    {"title": "Conclusion", "start_ms": 9400, "end_ms": 11250},
]


def test_vtt_structure_and_timestamps():
    vtt = build_vtt(SEGMENTS, CHAPTERS)
    lines = vtt.splitlines()

    assert lines[0] == "WEBVTT"
    assert "00:00:00.000 --> 00:00:03.400" in vtt
    assert "00:00:09.400 --> 00:00:11.250" in vtt
    # Les locuteurs sont balisés quand il y a un dialogue
    assert "<v Voix 1>Bonjour, il est sept heures trente." in vtt
    assert "<v Voix 2>La première brève du jour." in vtt
    assert "À demain." in vtt and "<v " not in lines[-2]  # segment sans locuteur


def test_vtt_timestamps_pass_the_hour():
    long_chapters = [{"title": "Intro", "start_ms": 3_723_456, "end_ms": 3_800_000}]
    assert "01:02:03.456" in build_vtt(SEGMENTS[:1], long_chapters)


def test_text_version_is_readable():
    text = build_text("Le Matin — vendredi 14 août", SEGMENTS)
    assert text.startswith("Le Matin — vendredi 14 août\n=")
    assert "Voix 1 — Bonjour" in text and "Voix 2 — La première" in text
    assert text.endswith("À demain.\n")


def test_write_transcript_creates_both_files(tmp_path):
    episode = tmp_path / "2026-08-14.mp3"
    assert write_transcript("Titre", SEGMENTS, CHAPTERS, episode) is True
    assert (tmp_path / "2026-08-14.vtt").read_text(encoding="utf-8").startswith("WEBVTT")
    assert "Titre" in (tmp_path / "2026-08-14.txt").read_text(encoding="utf-8")


def test_write_transcript_skips_vtt_without_matching_chapters(tmp_path):
    """Sans bornes fiables, on écrit le texte mais pas de VTT faux."""
    episode = tmp_path / "2026-08-14.mp3"
    assert write_transcript("Titre", SEGMENTS, CHAPTERS[:1], episode) is False
    assert (tmp_path / "2026-08-14.txt").exists()
    assert not (tmp_path / "2026-08-14.vtt").exists()


def test_write_transcript_without_segments(tmp_path):
    assert write_transcript("Titre", [], [], tmp_path / "e.mp3") is False


# ------------------------------------------------------------------- flux ---

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
  <channel>
    <item>
      <title>Épisode récent</title>
      <enclosure url="https://me.github.io/myop/episodes/matin/2026-08-14.mp3" type="audio/mpeg"/>
    </item>
    <item>
      <title>Épisode ancien</title>
      <enclosure url="https://me.github.io/myop/episodes/matin/2026-08-01.mp3" type="audio/mpeg"/>
    </item>
  </channel>
</rss>"""

BASE = "https://me.github.io/myop/"


def test_add_transcripts_targets_the_right_items():
    episodes = [{"id": "2026-08-14", "transcript": True}, {"id": "2026-08-01"}]
    xml = add_transcripts(FEED, BASE, "matin", episodes)

    assert 'xmlns:podcast="https://podcastindex.org/namespace/1.0"' in xml
    assert xml.count("<podcast:transcript") == 1  # l'ancien épisode n'en a pas
    assert f'url="{BASE}episodes/matin/2026-08-14.vtt"' in xml
    assert 'type="text/vtt"' in xml


def test_add_transcripts_is_a_noop_without_any():
    assert add_transcripts(FEED, BASE, "matin", [{"id": "2026-08-14"}]) == FEED


def test_feed_stays_parseable_after_injection():
    import xml.etree.ElementTree as ET

    xml = add_transcripts(FEED, BASE, "matin", [{"id": "2026-08-14", "transcript": True}])
    root = ET.fromstring(xml)
    items = root.find("channel").findall("item")
    ns = {"podcast": "https://podcastindex.org/namespace/1.0"}
    assert items[0].find("podcast:transcript", ns) is not None
    assert items[1].find("podcast:transcript", ns) is None
