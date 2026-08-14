"""Chapitrage ID3 des épisodes (frames CHAP/CTOC via mutagen).

Les lecteurs modernes (Apple Podcasts, Overcast, Pocket Casts) affichent
alors les sections de l'épisode et permettent la navigation directe.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.id3 import CHAP, CTOC, ID3, TIT2


def write_chapters(mp3_path: Path, chapters: list[dict]) -> None:
    """Écrit les chapitres (bornes en millisecondes) dans les tags ID3."""
    if not chapters:
        return

    tags = ID3(mp3_path) if mp3_path.exists() else ID3()
    # Nettoyage d'éventuels chapitres précédents (régénération)
    for key in list(tags.keys()):
        if key.startswith("CHAP") or key.startswith("CTOC"):
            del tags[key]

    child_ids = []
    for index, chapter in enumerate(chapters):
        chapter_id = f"chp{index + 1}"
        child_ids.append(chapter_id)
        tags.add(
            CHAP(
                encoding=3,
                element_id=chapter_id,
                start_time=int(chapter["start_ms"]),
                end_time=int(chapter["end_ms"]),
                sub_frames=[TIT2(encoding=3, text=chapter["title"])],
            )
        )

    # flags : 0x02 = table des matières de premier niveau
    tags.add(
        CTOC(
            encoding=3,
            element_id="toc",
            flags=2,
            child_element_ids=child_ids,
            sub_frames=[TIT2(encoding=3, text="Sommaire")],
        )
    )
    tags.save(mp3_path)


def read_chapter_titles(mp3_path: Path) -> list[str]:
    """Relit les titres de chapitres (usage : tests et vérifications)."""
    tags = ID3(mp3_path)
    titles = []
    for key in sorted(tags.keys()):
        if key.startswith("CHAP:"):
            for sub in tags[key].sub_frames.values():
                if isinstance(sub, TIT2) and sub.text:
                    titles.append(str(sub.text[0]))
    return titles
