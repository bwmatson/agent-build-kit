"""A child whose base branch has merged and whose retarget is pending gets one warning comment
on its pull request, recorded as the pipeline's own so the poller does not read it as a
reviewer's (spec: merge-landing).

The forge is the shared stand-in, which keeps what was posted; the rounds are driven by calling
the step directly."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pr_replies import MARKER, own_posts
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.forges.stand_in import FindingForge
from tests.pipeline.test_retarget_retry import (
    CHILD,
    PARENT,
    PULL,
    STALE_BASE,
    WANTED_BASE,
    child_behind_a_merged_parent,
)


class Round:
    """One store, one forge and the host's idea of each pull request's base."""

    def __init__(self, tmp_path: Path) -> None:
        self.store: UnitStore = child_behind_a_merged_parent(tmp_path)
        self.forge = FindingForge()
        self.root = tmp_path / "posts"
        self.root.mkdir()
        self.bases: dict[str, str] = {CHILD: STALE_BASE}
        self.asked: list[str] = []

    def base_on_host(self, unit: StoredUnit) -> str | None:
        self.asked.append(unit.id)
        return self.bases.get(unit.id)

    def forge_of(self, unit: StoredUnit) -> tuple[Forge, RepoId]:
        return self.forge, self.forge.repo_id()

    def run(self) -> list[str]:
        return events.warn_base_merged(
            self.store,
            base_on_host=self.base_on_host,
            forge_of=self.forge_of,
            posts_root=self.root,
            log=lambda _line: None,
        )

    def own(self) -> set[str]:
        return own_posts(self.root, forges.key(self.forge.repo_id()), PULL)


def test_a_child_whose_retarget_is_pending_gets_one_comment_with_the_marker_line(
    tmp_path: Path,
) -> None:
    warn = Round(tmp_path)

    warn.run()

    [comment] = warn.forge.comments
    assert MARKER in comment
    assert WANTED_BASE in comment
    assert "Do not merge" in comment
    assert warn.forge.calls == [("comment", PULL)]


def test_the_comment_is_recorded_in_the_own_posts_record(tmp_path: Path) -> None:
    warn = Round(tmp_path)

    warn.run()

    assert warn.own() == {"comment-1"}


def test_no_second_comment_follows_while_the_retarget_stays_pending(tmp_path: Path) -> None:
    warn = Round(tmp_path)

    rounds = [warn.run() for _ in range(3)]

    assert len(warn.forge.comments) == 1
    assert rounds == [[CHILD], [], []]


def test_a_failed_retarget_that_holds_the_unit_does_not_bring_a_second_comment(
    tmp_path: Path,
) -> None:
    warn = Round(tmp_path)
    warn.run()
    warn.store.set_base_move_failures(CHILD, 2)

    warn.run()

    assert len(warn.forge.comments) == 1


def test_a_child_already_on_its_base_gets_no_comment(tmp_path: Path) -> None:
    warn = Round(tmp_path)
    warn.bases[CHILD] = WANTED_BASE

    warned = warn.run()

    assert warned == []
    assert warn.forge.comments == []


def test_a_child_whose_base_branch_has_not_merged_gets_no_comment(tmp_path: Path) -> None:
    warn = Round(tmp_path)
    warn.store.set_state(PARENT, IN_REVIEW, pr=1, branch=STALE_BASE)

    warned = warn.run()

    assert warned == []
    assert warn.forge.comments == []


def test_the_host_is_not_asked_about_a_unit_with_no_merged_base(tmp_path: Path) -> None:
    warn = Round(tmp_path)
    warn.store.set_state(PARENT, IN_REVIEW, pr=1, branch=STALE_BASE)

    warn.run()

    assert warn.asked == []


def test_a_child_whose_host_base_is_unknown_gets_no_comment(tmp_path: Path) -> None:
    warn = Round(tmp_path)
    warn.bases.clear()

    warn.run()

    assert warn.forge.comments == []


def test_a_comment_the_host_refuses_is_not_recorded_and_is_tried_again(tmp_path: Path) -> None:
    warn = Round(tmp_path)
    warn.forge.comment_error = True

    warn.run()

    assert warn.own() == set()
    warn.forge.comment_error = False
    warn.run()
    assert len(warn.forge.comments) == 1
    assert warn.own() == {"comment-1"}
