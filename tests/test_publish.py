"""Tests publication : cron Paris → UTC, réécriture du workflow, URL Pages, historique."""

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Config, Show
from app.publish import (
    _merge_key_set,
    cron_for,
    crons_for,
    pages_base_for,
    prune_published_episodes,
    update_workflow_schedule,
)

PARIS = ZoneInfo("Europe/Paris")

WORKFLOW_SAMPLE = """name: Épisode quotidien

on:
  schedule:
    # commentaire à préserver
    - cron: "26 * * * *"
  workflow_dispatch: {}

permissions:
  contents: write
"""


def test_cron_summer_time():
    # Été (UTC+2) : 7h30 Paris = 5h30 UTC
    summer = datetime(2026, 8, 14, tzinfo=PARIS)
    assert cron_for("07:30", now=summer) == "30 5 * * *"


def test_cron_winter_time():
    # Hiver (UTC+1) : 7h30 Paris = 6h30 UTC
    winter = datetime(2026, 1, 14, tzinfo=PARIS)
    assert cron_for("07:30", now=winter) == "30 6 * * *"


def test_cron_crosses_midnight():
    # 00h30 Paris en été = 22h30 UTC la veille
    summer = datetime(2026, 8, 14, tzinfo=PARIS)
    assert cron_for("00:30", now=summer) == "30 22 * * *"


def test_crons_cover_both_daylight_saving_variants():
    """Une heure de livraison → deux crons UTC, pour être juste toute l'année."""
    config = Config(shows=[Show(id="matin", delivery_hour="07:30")])
    assert crons_for(config, reference=datetime(2026, 8, 14, tzinfo=PARIS)) == [
        "30 5 * * *",  # été
        "30 6 * * *",  # hiver
    ]


def test_crons_deduplicate_and_ignore_disabled_shows():
    config = Config(
        shows=[
            Show(id="matin", delivery_hour="07:30"),
            Show(id="autre", delivery_hour="07:30"),  # même heure : un seul cron
            Show(id="soir", delivery_hour="18:00"),
            Show(id="pause", delivery_hour="23:00", enabled=False),
        ]
    )
    crons = crons_for(config, reference=datetime(2026, 8, 14, tzinfo=PARIS))
    assert crons == ["30 5 * * *", "30 6 * * *", "0 16 * * *", "0 17 * * *"]
    assert len(crons) == 4  # 24 exécutions/jour → 4


def test_update_workflow_schedule_rewrites_the_block(tmp_path):
    workflow = tmp_path / "daily.yml"
    workflow.write_text(WORKFLOW_SAMPLE, encoding="utf-8")
    config = Config(shows=[Show(id="matin", delivery_hour="08:00")])

    update_workflow_schedule(config, path=workflow)

    content = workflow.read_text(encoding="utf-8")
    assert re.findall(r'- cron: "([^"]+)"', content) == ["0 6 * * *", "0 7 * * *"]
    # Indentation, commentaire et reste du workflow intacts
    assert '    - cron: "0 6 * * *"\n' in content
    assert "# commentaire à préserver" in content
    assert "workflow_dispatch" in content and "permissions:" in content


def test_update_workflow_schedule_is_idempotent(tmp_path):
    workflow = tmp_path / "daily.yml"
    workflow.write_text(WORKFLOW_SAMPLE, encoding="utf-8")
    config = Config(shows=[Show(id="matin", delivery_hour="08:00")])

    update_workflow_schedule(config, path=workflow)
    once = workflow.read_text(encoding="utf-8")
    update_workflow_schedule(config, path=workflow)

    assert workflow.read_text(encoding="utf-8") == once


def test_pages_base_for_project_and_user_site():
    assert pages_base_for("moi/myop") == "https://moi.github.io/myop/"
    # Repo « user.github.io » : le site est à la racine du domaine
    assert pages_base_for("moi/moi.github.io") == "https://moi.github.io/"
    assert pages_base_for("Moi/Moi.GitHub.io") == "https://Moi.github.io/"


def test_merge_key_set_unions_local_and_remote(tmp_path):
    """L'historique distant complète le local sans jamais l'écraser."""
    local = tmp_path / "seen-matin.json"
    local.write_text(json.dumps(["a", "b"]), encoding="utf-8")

    _merge_key_set(local, json.dumps(["b", "c"]))

    assert set(json.loads(local.read_text(encoding="utf-8"))) == {"a", "b", "c"}


def test_merge_key_set_survives_corrupted_content(tmp_path):
    local = tmp_path / "seen-matin.json"
    local.write_text("{pas du json", encoding="utf-8")

    _merge_key_set(local, json.dumps(["c"]))

    assert json.loads(local.read_text(encoding="utf-8")) == ["c"]


def test_merge_key_set_creates_missing_file(tmp_path):
    local = tmp_path / "nested" / "seen-soir.json"

    _merge_key_set(local, json.dumps(["x"]))

    assert json.loads(local.read_text(encoding="utf-8")) == ["x"]


# ------------------------------------------------------ rétention gh-pages ---

def _episodes(root, show_id: str, ids: list[str], *, audio: bool = True) -> None:
    folder = root / "episodes" / show_id
    folder.mkdir(parents=True, exist_ok=True)
    for episode_id in ids:
        (folder / f"{episode_id}.json").write_text("{}", encoding="utf-8")
        if audio:
            (folder / f"{episode_id}.mp3").write_bytes(b"x")


def test_prune_published_removes_episodes_older_than_the_local_window(tmp_path):
    dist, worktree = tmp_path / "dist", tmp_path / "publish"
    _episodes(dist, "matin", ["2026-08-13", "2026-08-14", "2026-08-15"], audio=False)
    _episodes(worktree, "matin", ["2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"])

    removed = prune_published_episodes(dist, worktree, keep=3)

    published = {p.name for p in (worktree / "episodes" / "matin").iterdir()}
    assert published == {"2026-08-13.json", "2026-08-13.mp3", "2026-08-14.json", "2026-08-14.mp3"}
    assert len(removed) == 4  # les .json et .mp3 des 11 et 12 août


def test_prune_published_does_nothing_without_enough_local_history(tmp_path):
    """Publier sans avoir récupéré l'historique distant ne doit rien effacer."""
    dist, worktree = tmp_path / "dist", tmp_path / "publish"
    _episodes(dist, "matin", ["2026-08-15"], audio=False)
    _episodes(worktree, "matin", ["2026-08-01", "2026-08-02", "2026-08-15"])

    assert prune_published_episodes(dist, worktree, keep=3) == []
    assert len(list((worktree / "episodes" / "matin").iterdir())) == 6


def test_prune_published_is_per_show(tmp_path):
    dist, worktree = tmp_path / "dist", tmp_path / "publish"
    _episodes(dist, "matin", ["2026-08-14", "2026-08-15"], audio=False)
    _episodes(dist, "soir", ["2026-08-15"], audio=False)
    _episodes(worktree, "matin", ["2026-08-01", "2026-08-14", "2026-08-15"])
    _episodes(worktree, "soir", ["2026-08-01", "2026-08-15"])

    prune_published_episodes(dist, worktree, keep=2)

    assert not (worktree / "episodes" / "matin" / "2026-08-01.mp3").exists()
    assert (worktree / "episodes" / "soir" / "2026-08-01.mp3").exists()  # trop peu d'historique


def test_vercel_url_prefers_the_stable_alias():
    """La CLI répond en JSON hors terminal : l'URL se cherche, ne se déduit pas."""
    from app.publish import vercel_url

    output = (
        "Production: https://myop-6tstxhxpz-rens-projects.vercel.app [4s]\n"
        "Completing...\n"
        "Aliased: https://myop-flax.vercel.app [4s]\n"
        '{\n  "status": "ok",\n  "message": "Deployment ready."\n}'
    )
    assert vercel_url(output) == "https://myop-flax.vercel.app"


def test_vercel_url_falls_back_to_the_deployment_url():
    from app.publish import vercel_url

    assert (
        vercel_url('{"url": "https://myop-abc.vercel.app", "readyState": "READY"}')
        == "https://myop-abc.vercel.app"
    )
    assert vercel_url("rien d'utile ici") is None


def test_link_vercel_project_writes_the_link(tmp_path):
    from app.config import Config
    from app.publish import link_vercel_project

    config = Config(publishing={"vercel_project_id": "prj_1", "vercel_org_id": "team_1"})
    assert link_vercel_project(tmp_path, config) is True
    assert json.loads((tmp_path / ".vercel" / "project.json").read_text(encoding="utf-8")) == {
        "projectId": "prj_1",
        "orgId": "team_1",
    }


def test_link_vercel_project_needs_both_identifiers(tmp_path):
    from app.config import Config
    from app.publish import link_vercel_project

    assert link_vercel_project(tmp_path, Config()) is False
    assert not (tmp_path / ".vercel").exists()


def test_prune_published_disabled_by_zero(tmp_path):
    dist, worktree = tmp_path / "dist", tmp_path / "publish"
    _episodes(dist, "matin", ["2026-08-15"], audio=False)
    _episodes(worktree, "matin", ["2026-01-01", "2026-08-15"])

    assert prune_published_episodes(dist, worktree, keep=0) == []
