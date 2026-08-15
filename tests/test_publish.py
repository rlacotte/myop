"""Tests publication : cron Paris → UTC, réécriture du workflow, URL Pages, historique."""

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.publish import _merge_key_set, cron_for, pages_base_for, update_workflow_cron

PARIS = ZoneInfo("Europe/Paris")

WORKFLOW_SAMPLE = """name: Épisode quotidien

on:
  schedule:
    - cron: "30 5 * * *"
  workflow_dispatch: {}
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


def test_update_workflow_cron_rewrites_line(tmp_path):
    workflow = tmp_path / "daily.yml"
    workflow.write_text(WORKFLOW_SAMPLE, encoding="utf-8")
    update_workflow_cron("08:00", path=workflow)

    content = workflow.read_text(encoding="utf-8")
    match = re.search(r'- cron: "([^"]+)"', content)
    assert match and match.group(1) == "0 6 * * *"  # 8h Paris en été = 6h UTC
    assert "workflow_dispatch" in content  # le reste du workflow est intact


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
