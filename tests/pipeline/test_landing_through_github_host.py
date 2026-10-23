"""A landing proved end to end through the GitHub adapter and the poller (spec: auto-land).

The host is the GitHub stand-in answering at the HTTP boundary. Its merge route is scripted to do
what GitHub does, mark the pull request merged, so the poller's later listing shows it so. The
pull requests are seeded with the checks GitHub's listing carries; the comment and label a
landing adds are best-effort and not what is under test here, so the stand-in is not asked to
answer them."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.archive import is_ready_to_archive
from agent_build_kit.pipeline.landing_intent import LANDING
from agent_build_kit.pipeline.pr_poller import Poller, state_path
from agent_build_kit.pipeline.ui_review import ui_listing, unit_of
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.verify import Verification
from agent_build_kit.settings import settings
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges import github_answers
from tests.forges.github_host import GitHubHost, answer
from tests.forges.github_routes import GitHubState
from tests.landing_support import HEAD, apply_review, listed_review
from tests.verdict_fakes import write_verdicts

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
SQUASHED = "b" * 40
GREEN = [github_answers.check_run(name, "SUCCESS") for name in ("build", "lint", "test")]


def merge_path(pr: int) -> str:
    return f"{BASE}/pulls/{pr}/merge"


@pytest.fixture(autouse=True)
def github_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "gh_token", "gh-secret")
    clear_credentials()
    yield
    clear_credentials()


class Pipeline:
    """Units `c/1` and `c/2` (on `c/1`) in review, their pull requests on the GitHub stand-in,
    the landing pass and the poller over it."""

    def __init__(
        self, tmp_path: Path, patch: pytest.MonkeyPatch, *, checks: list[dict[str, Any]] | None
    ) -> None:
        self.inst: Installation = make_installation(tmp_path)
        apply_review(self.inst, listed_review())
        self.inst.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = UnitStore(self.inst.state_dir / "units.json")
        self.store.import_units(
            [stored_unit("c/1", change="c"), stored_unit("c/2", change="c", depends_on=("c/1",))]
        )
        for number in (1, 2):
            self.store.set_state(f"c/{number}", IN_REVIEW, pr=number, branch=f"spec/c/{number}")
            self.store.record_approval(f"c/{number}", HEAD)
            self.store.record_push(f"c/{number}", HEAD)
        write_verdicts(
            self.inst.state_dir / VERDICTS,
            dict.fromkeys(("c/1", "c/2"), ReviewTier.AUTO),
            unit_class="docs",
        )
        self.state = GitHubState(
            github_answers.pull(1, head="spec/c/1", checks=checks),
            github_answers.pull(2, head="spec/c/2", base="spec/c/1", checks=checks),
        )
        self.host = GitHubHost(
            state=self.state, routes={("PUT", merge_path(n)): self._merge(n) for n in (1, 2)}
        )
        forge = GitHubForge(http=self.host)
        patch.setattr(self.inst, "forge_of", lambda repo: (forge, REPO))
        self.restacked: list[tuple[str, str, str]] = []
        self.retargeted: list[tuple[str, str]] = []
        self.logged: list[str] = []
        self.dispatch = events.build_dispatch(
            self.store,
            restack=lambda **k: self.restacked.append((k["branch"], k["old_base"], k["new_base"])),
            remove_worktree=lambda repo, branch: None,
            delete_branch=lambda repo, branch: None,
            retarget=lambda unit, base: self.retargeted.append((unit.id, base)),
            rebase_cap=2,
            landing_path=self.inst.state_dir / LANDING,
            log=lambda message: None,
        )
        self.poller = Poller(
            repo="app",
            state_path=state_path(self.inst.state_dir, "app"),
            dispatch=self.dispatch,
            list_prs=ui_listing(self.inst, self.store, "app"),
            unit_of=lambda number: unit_of(self.store, "app", number),
            log=self.logged.append,
        )

    def _merge(self, number: int):
        def merge(request: httpx.Request) -> httpx.Response:
            self.state.stored(number).update(state="MERGED", mergedAt="2026-10-01T12:00:00Z")
            return answer({"sha": SQUASHED, "merged": True, "message": "merged"})

        return merge

    def land(self) -> None:
        cli.land_units(self.inst, self.store, dispatch=self.dispatch, say=self.logged.append)

    def unit(self, unit_id: str) -> StoredUnit:
        return self.store.get(unit_id)


def test_a_unit_with_green_checks_lands_with_a_squash_request_at_its_approved_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = Pipeline(tmp_path, monkeypatch, checks=GREEN)
    pipeline.poller.poll()

    pipeline.land()

    [call] = pipeline.host.calls("PUT", merge_path(1))
    assert call.body["merge_method"] == "squash"
    assert call.body["sha"] == HEAD
    landed = pipeline.unit("c/1")
    assert (landed.state, landed.cause) == (MERGED, Cause.AUTO_LANDED), "\n".join(pipeline.logged)
    assert pipeline.host.calls("POST", f"{BASE}/issues/1/comments"), "the landing is said on the PR"


def test_the_poller_s_later_merged_event_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = Pipeline(tmp_path, monkeypatch, checks=GREEN)
    pipeline.poller.poll()
    pipeline.land()
    history = pipeline.unit("c/1").history
    restacked = list(pipeline.restacked)

    pipeline.poller.poll()

    assert pipeline.unit("c/1").history == history
    assert pipeline.restacked == restacked
    assert len(pipeline.host.calls("PUT", merge_path(1))) == 1


def test_a_stacked_child_of_the_landed_unit_is_retargeted_and_restacked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = Pipeline(tmp_path, monkeypatch, checks=GREEN)
    pipeline.poller.poll()

    pipeline.land()

    assert ("c/2", "main") in pipeline.retargeted, "\n".join(pipeline.logged)
    assert ("spec/c/2", "spec/c/1", "main") in pipeline.restacked


def test_verify_and_archive_treat_the_change_as_merged_once_its_units_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = Pipeline(tmp_path, monkeypatch, checks=GREEN)
    pipeline.poller.poll()
    pipeline.land()
    pipeline.poller.poll()
    pipeline.land()
    verified: list[str] = []

    def verify(change: str, units: list[StoredUnit]) -> Verification:
        verified.append(change)
        return Verification(change=change, passed=True, units=["c/1", "c/2"])

    may_archive = cli.verify_ready(pipeline.inst, pipeline.store.all(), verify=verify)

    assert {u.id: u.state for u in pipeline.store.all()} == {"c/1": MERGED, "c/2": MERGED}
    assert is_ready_to_archive("c", pipeline.store.all())
    assert verified == ["c"]
    assert may_archive("c")


def test_a_pull_request_with_no_checks_registered_sends_nothing_to_the_merge_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline = Pipeline(tmp_path, monkeypatch, checks=None)
    pipeline.poller.poll()

    pipeline.land()

    assert pipeline.host.calls("PUT") == []
    assert pipeline.unit("c/1").state == IN_REVIEW
    assert any("no checks" in line for line in pipeline.logged), "\n".join(pipeline.logged)
