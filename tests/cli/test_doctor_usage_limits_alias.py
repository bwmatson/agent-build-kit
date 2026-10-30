"""`abk doctor` warns, and does not fail, for a runtime that still says `limits`."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

WINDOWS = "    {key}:\n      session:\n        usage_pause_pct: 60\n"


def doctor(tmp_path: Path, key: str) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(
        "version: 1\nruntimes:\n  claude_code:\n" + WINDOWS.format(key=key)
    )
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def test_the_old_key_is_a_warning_with_the_rename_notice_and_no_failure(tmp_path: Path) -> None:
    checks = doctor(tmp_path, "limits")

    warned = [c for c in checks if c.status == "warn" and "usage_limits" in c.detail]
    assert len(warned) == 1
    assert "`runtimes.claude_code.limits` is renamed `usage_limits`" in warned[0].detail
    assert "abk config --migrate" in warned[0].detail
    assert [c for c in checks if c.name == "config"][0].status == "ok"
