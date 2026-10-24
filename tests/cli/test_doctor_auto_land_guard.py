"""`abk doctor` warns when a class may land and nothing server-side guards the branch
(spec: auto-land)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit import forges
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig
from agent_build_kit.forges import RepoId
from tests.cli.test_doctor import Answers
from tests.factories import init_repo, which_all
from tests.forges.stand_in import StandInForge

UNPROTECTED = "no branch protection on main"

REVIEW = {"enabled": True, "classes": {"docs": ["docs/**"]}}
LISTED = {**REVIEW, "auto_land": {"classes": ["docs"]}}


class PerRepoHost(StandInForge):
    """The registered `github` forge, whose branch protection is told repo by repo."""

    name = "github"

    def __init__(self, unprotected: set[str]) -> None:
        super().__init__()
        self.unprotected = unprotected

    def identity(self, repo: RepoConfig) -> RepoId:
        return RepoId(forge=self.name, account="example", name=(repo.slug or "").split("/")[-1])

    def merge_guard(self, repo: RepoId, *, branch: str, run: Any = None) -> str:
        return UNPROTECTED if repo.name in self.unprotected else ""


def doctor(tmp_path: Path, review: dict[str, Any], *, unprotected: set[str]) -> list[Check]:
    """Doctor over `app` and `platform`, each holding `docs/guide.md`; `unprotected` names the
    repos whose host reports no branch protection."""
    forges.register(PerRepoHost(unprotected))
    planning = init_repo(tmp_path / "planning")
    repos = {}
    for name in ("app", "platform"):
        path = init_repo(tmp_path / name)
        (path / "docs").mkdir()
        (path / "docs" / "guide.md").write_text("")
        repos[name] = {"path": str(path), "slug": f"example/{name}"}
    (planning / "abk.yaml").write_text(yaml.safe_dump({"repos": repos, "review": review}))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def guard_of(checks: list[Check], repo: str) -> Check:
    return next(c for c in checks if c.name == f"merge guard {repo}")


def said(check: Check) -> str:
    return f"{check.name} {check.detail} {check.fix}"


def test_an_unprotected_repo_warns_that_the_policy_hook_is_then_the_only_guard(
    tmp_path: Path,
) -> None:
    checks = doctor(tmp_path, LISTED, unprotected={"app"})

    check = guard_of(checks, "app")
    assert check.status == "warn"
    assert "hook" in said(check)
    assert "only guard" in said(check)
    assert "pipeline's own merge" in said(check)


def test_each_repo_is_reported_on_its_own(tmp_path: Path) -> None:
    checks = doctor(tmp_path, LISTED, unprotected={"platform"})

    assert guard_of(checks, "app").status == "ok"
    assert guard_of(checks, "platform").status == "warn"
    assert [c for c in checks if c.status == "warn" and "only guard" in said(c)] == [
        guard_of(checks, "platform")
    ]


def test_the_guard_is_information_with_no_class_listed_and_a_warning_once_one_is(
    tmp_path: Path,
) -> None:
    empty = doctor(tmp_path / "empty", REVIEW, unprotected={"app"})
    listed = doctor(tmp_path / "listed", LISTED, unprotected={"app"})

    assert guard_of(empty, "app").status == "info"
    assert "pipeline's own merge" not in said(guard_of(empty, "app"))
    assert guard_of(listed, "app").status == "warn"


def test_a_list_with_review_enabled_is_not_warned_to_have_no_effect(tmp_path: Path) -> None:
    checks = doctor(tmp_path, LISTED, unprotected={"app"})

    assert [c for c in checks if "no effect" in said(c)] == []
    assert guard_of(checks, "app").status == "warn"
