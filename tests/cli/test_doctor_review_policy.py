"""`abk doctor` checks the `review` section (spec: review-policy)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import load
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo


def doctor(tmp_path: Path, review: dict[str, Any]) -> list[Check]:
    """Doctor over a planning repo and an `app` repo holding `src/app.py` and `docs/guide.md`."""
    planning = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    (app / "src").mkdir()
    (app / "src" / "app.py").write_text("")
    (app / "docs").mkdir()
    (app / "docs" / "guide.md").write_text("")
    document = {
        "repos": {"app": {"path": str(app), "slug": "example/app"}},
        "review": review,
    }
    (planning / "abk.yaml").write_text(yaml.safe_dump(document))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def about_review(checks: list[Check], status: str) -> list[Check]:
    return [c for c in checks if c.status == status and c.name.startswith("review")]


VALID = {
    "enabled": True,
    "protected_paths": ["src/**"],
    "classes": {"docs": ["docs/**"]},
}


def test_a_valid_section_is_silent(tmp_path: Path) -> None:
    checks = doctor(tmp_path, VALID)

    assert load(tmp_path / "planning" / "abk.yaml").review.model_dump()["enabled"] is True
    assert about_review(checks, "warn") == []
    assert about_review(checks, "FAIL") == []


def test_a_protected_glob_that_matches_no_file_in_any_repo_is_warned_about_naming_it(
    tmp_path: Path,
) -> None:
    checks = doctor(tmp_path, {**VALID, "protected_paths": ["servcies/**", "src/**"]})

    found = about_review(checks, "warn")
    assert len(found) == 1
    assert "servcies/**" in f"{found[0].name} {found[0].detail}"
    assert about_review(checks, "FAIL") == []


def test_a_class_glob_that_matches_no_file_is_warned_about_naming_it_and_the_class(
    tmp_path: Path,
) -> None:
    checks = doctor(tmp_path, {**VALID, "classes": {"docs": ["docs/**"], "notes": ["notes/**"]}})

    found = about_review(checks, "warn")
    assert len(found) == 1
    assert "notes/**" in f"{found[0].name} {found[0].detail}"
    assert "notes" in f"{found[0].name} {found[0].detail}"


def test_a_class_that_cannot_be_resolved_is_a_failure(tmp_path: Path) -> None:
    checks = doctor(tmp_path, {**VALID, "classes": {"docs": ["../outside/**"]}})

    found = about_review(checks, "FAIL") or [
        c for c in checks if c.status == "FAIL" and "docs" in f"{c.name} {c.detail}"
    ]
    assert found
    assert "docs" in f"{found[0].name} {found[0].detail}"


def test_policy_set_while_review_is_not_enabled_is_warned_about(tmp_path: Path) -> None:
    checks = doctor(tmp_path, {**VALID, "enabled": False})

    found = about_review(checks, "warn")
    assert len(found) == 1
    assert "enabled" in f"{found[0].name} {found[0].detail}"
    assert about_review(checks, "FAIL") == []


def test_a_section_with_nothing_set_and_review_off_is_silent(tmp_path: Path) -> None:
    checks = doctor(tmp_path, {"enabled": False})

    assert load(tmp_path / "planning" / "abk.yaml").review.model_dump()["enabled"] is False
    assert about_review(checks, "warn") == []
    assert about_review(checks, "FAIL") == []
