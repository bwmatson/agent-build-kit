"""`abk doctor` and the split settings: buffered ceilings and the rounds (spec: hold-and-split)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, review: dict[str, Any]) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    document = {
        "repos": {"app": {"path": str(app), "slug": "example/app"}},
        "review": review,
    }
    (planning / "abk.yaml").write_text(yaml.safe_dump(document))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def about_review(checks: list[Check], status: str) -> list[Check]:
    return [c for c in checks if c.status == status and c.name.startswith("review")]


def text(check: Check) -> str:
    return f"{check.name} {check.detail} {check.fix}"


def test_the_defaults_print_the_buffered_ceilings_and_warn_of_nothing(tmp_path: Path) -> None:
    checks = doctor(tmp_path, {"enabled": True})

    printed = [c for c in checks if c.name.startswith("review") and "900" in text(c)]
    assert printed
    assert "6000" in text(printed[0])
    assert "2400" in text(printed[0])
    assert about_review(checks, "warn") == []
    assert about_review(checks, "FAIL") == []


def test_an_auto_ceiling_of_7000_with_the_default_buffer_is_warned_about(tmp_path: Path) -> None:
    checks = doctor(tmp_path, {"enabled": True, "ceilings": {"auto": 7000}})

    found = [c for c in about_review(checks, "warn") if "8400" in text(c)]
    assert len(found) == 1
    assert "limit" in text(found[0])


def test_zero_rounds_with_review_enabled_is_warned_about(tmp_path: Path) -> None:
    checks = doctor(tmp_path, {"enabled": True, "split_rounds": 0})

    found = [c for c in about_review(checks, "warn") if "split_rounds" in text(c)]
    assert len(found) == 1
