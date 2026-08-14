"""Tests de la conversion heure Paris → cron UTC et de la réécriture du workflow."""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.publish import cron_for, update_workflow_cron

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


def test_cron_other_hour():
    morning = datetime(2026, 8, 14, tzinfo=PARIS)
    assert cron_for("08:00", now=morning) == "0 6 * * *"


def test_update_workflow_cron_rewrites_line(tmp_path):
    workflow = tmp_path / "daily.yml"
    workflow.write_text(WORKFLOW_SAMPLE, encoding="utf-8")
    update_workflow_cron("08:00", path=workflow)

    content = workflow.read_text(encoding="utf-8")
    match = re.search(r'- cron: "([^"]+)"', content)
    assert match
    assert match.group(1) == "0 6 * * *"  # 8h00 Paris en été = 6h00 UTC
    # Le reste du workflow est intact
    assert "workflow_dispatch" in content
