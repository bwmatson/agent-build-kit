"""A commit whose subject does not follow the convention is not counted toward a group's pair,
whether it was made by hand or adopted as it was: the stop for a missing pair still raises, and
the subject the pipeline would give the next adopted commit is still the group's own (spec:
attach-commit-subject)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.commit_order import adopted_subject
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.stack_runner import GroupStep, RunOutcome
from agent_build_kit.pipeline.unit_store import RewriteSource, StoredRewriteRequest, StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, branch_name
from packages.worker.tests.graph.test_build_path import build
from tests.factories import stored_unit, unit
from tests.graph.branch_fakes import (
    TRAILER,
    UNIT,
    OnBranch,
    agent_calls,
    built,
    built_after_a_pair,
    group_trailers,
    key,
    land_grouped,
    messages,
    prepared,
    subjects,
    titled,
)

HAND_MADE = "Release the unit after the config edit"
PAIR_4 = "the branch holds no tests and implementation pair for group 4 (G4)"
PAIR = "the branch holds no tests and implementation pair for group 3 (G3)"


def test_a_hand_made_commit_with_a_free_text_subject_is_not_counted_and_the_stop_raises(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(
        tmp_path,
        groups={"add-marker": titled(3)},
        seeded=["test: G3", HAND_MADE],
        no_commit_for="3",
        unit_test_ok=False,
        asked=True,
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert subjects(repo) == ["test: G3", HAND_MADE]
    group = GroupStep(change_dir="changes/add-marker", number=3, title="G3")
    assert adopted_subject("Add the marker", (group,), subjects(repo)) == "feat: G3", (
        "the free-text commit is not counted, and a feat: adopted after it cannot pair across it "
        "either: the stop still raises"
    )


def test_every_commit_a_stubbed_build_makes_for_a_group_carries_the_groups_trailer(
    tmp_path: Path,
) -> None:
    """Group 3 is built by real tests and implementation commits, group 4 by an empty recorded-built
    pair, and each carries `Group: <change>/<number>` beside `Unit:`."""
    _, outcome, repo = built_after_a_pair(tmp_path)

    assert outcome.status != "failed", outcome.detail
    made = messages(repo)
    assert len(made) == 4
    assert all(TRAILER in message for message in made)
    assert group_trailers(repo) == [f"add-marker/{number}" for number in (3, 3, 4, 4)]


@pytest.mark.parametrize(
    ("seeded", "no_commit_for", "pair", "found"),
    [
        (["test: G3", HAND_MADE], "3", PAIR, "test: G3"),
        # A free-text commit stands where group 4's tests belong: the stop names it. (A seed of
        # an older title at group 3's own place never reaches the stop: the build commits that
        # group's tests after it and goes on, so the place is tested at group 4.)
        (["test: G3", "feat: G3", HAND_MADE], "4", PAIR_4, HAND_MADE),
    ],
)
def test_the_stop_names_the_subject_found_at_the_groups_place(
    tmp_path: Path, seeded: list[str], no_commit_for: str, pair: str, found: str
) -> None:
    recorder, _ = prepared(
        tmp_path,
        groups={"add-marker": titled(3, 4)},
        seeded=seeded,
        no_commit_for=no_commit_for,
        unit_test_ok=False,
        asked=True,
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert pair in outcome.detail
    assert f"found `{found}` at its place" in outcome.detail


def test_a_pair_under_an_older_title_is_counted_by_its_trailer_and_the_note_is_said_once(
    tmp_path: Path,
) -> None:
    def earlier(repo: Path) -> None:
        land_grouped(repo, "test: Old G3", "add-marker/3")
        land_grouped(repo, "feat: Old G3", "add-marker/3")

    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": titled(3, 4)}, meanwhile=earlier
    )

    assert outcome.status != "failed", outcome.detail
    assert subjects(repo) == ["test: Old G3", "feat: Old G3", "test: G4", "feat: G4"]
    said = [line for line in recorder.logged if "Old G3" in line]
    assert len(said) == 1, said
    assert "`test: Old G3`" in said[0]
    assert "`feat: Old G3`" in said[0]


SHAPE_COMMAND = "abk requeue --rework --rewrite"
STALE_12 = ["test: G11", "feat: G11", "test: Old G12", "feat: G12"]
STOP_12 = "the branch holds no commit for group 12 (G12); found `test: Old G12` at its place"
Rework = Callable[[Path], None]


def squash_group_12(cwd: Path) -> None:
    """What a rework that honours the request does: group 12's commits become one `feat:`."""
    git(cwd, "reset", "-q", "--hard", "HEAD~2")
    (cwd / "group-12.txt").write_text("feat: G12\n")
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", f"feat: G12\n\n{TRAILER}\nGroup: add-marker/12\n")


def add_a_feat(cwd: Path) -> None:
    """What a rework that rewrites nothing does: it adds another commit on top."""
    (cwd / f"more-{len(list(cwd.iterdir()))}.txt").write_text("feat: G12\n")
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", f"feat: G12\n\n{TRAILER}\nGroup: add-marker/12\n")


def stale_group_12(tmp_path: Path, *, asked: bool = False) -> tuple[OnBranch, Path]:
    """A unit of groups 11 to 13, group 12 headed `refactor`, whose branch holds group 12's
    commits as `test: Old G12` then `feat: G12`, and whose build stops there."""
    return prepared(
        tmp_path,
        groups={"add-marker": titled(11, 12, 13)},
        modes={key(12): "refactor"},
        seeded=STALE_12,
        no_commit_for="12",
        unit_test_ok=False,
        asked=asked,
    )


def stopped_at_stale_group_12(
    tmp_path: Path, rework: Rework
) -> tuple[OnBranch, Path, RunOutcome, list[StoredUnit]]:
    """The build of `stale_group_12`. `rework` is what the agent does in a step that may
    rewrite; the unit the store held as each such step began is returned last."""
    recorder, repo = stale_group_12(tmp_path)
    original = recorder.claude
    held: list[StoredUnit] = []

    def claude(prompt: str, **kwargs: Any) -> str:
        if not kwargs.get("rewrite"):
            return original(prompt, **kwargs)
        held.append(recorder.store.get(UNIT))
        recorder.prompts.append(prompt)
        recorder.rewrites.append(True)
        rework(kwargs["cwd"])
        recorder.unit_test_ok = True  # the rewritten branch is a green one
        return "done"

    recorder.claude = claude
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))
    return recorder, repo, outcome, held


def test_a_shape_stop_stores_the_checks_own_request_and_the_next_step_is_the_rework_with_it(
    tmp_path: Path,
) -> None:
    recorder, _, _, held = stopped_at_stale_group_12(tmp_path, squash_group_12)

    assert held, "a step that may rewrite ran after the stop"
    request = held[0].rewrite_request
    assert request is not None
    assert request.source is RewriteSource.COMMIT_SHAPE
    assert STOP_12 in request.text
    assert "feat: G12" in request.text, "the one commit group 12 takes"
    assert any(e.get("event") == "rewrite_requested" for e in held[0].history)
    assert any(request.text in prompt for prompt in recorder.prompts), "the rework was given it"


def test_a_rework_that_squashes_the_group_lets_the_build_go_on_with_no_person(
    tmp_path: Path,
) -> None:
    recorder, repo, outcome, _ = stopped_at_stale_group_12(tmp_path, squash_group_12)

    assert outcome.status != "failed", outcome.detail
    assert subjects(repo)[:3] == ["test: G11", "feat: G11", "feat: G12"]
    assert recorder.store.get(UNIT).rewrite_request is None
    assert agent_calls(recorder.events)[-2:] == ["claude:tests", "claude:impl"], "group 13"


def test_a_rework_that_only_adds_a_commit_fails_the_unit_with_the_stop_and_the_kept_head(
    tmp_path: Path,
) -> None:
    recorder, repo, outcome, _ = stopped_at_stale_group_12(tmp_path, add_a_feat)

    kept = git_out(repo, "for-each-ref", "--format=%(refname)", "refs/abk/before-rewrite/").split()
    assert outcome.status == "failed"
    assert STOP_12 in outcome.detail
    assert "rewrite" in outcome.detail.lower(), "it says a rewrite was asked and not made"
    assert len(kept) == 1 and kept[0] in outcome.detail
    assert git_out(repo, "rev-parse", "HEAD") == git_out(repo, "rev-parse", kept[0])
    assert subjects(repo) == STALE_12, "the branch is back at the head the rework began on"
    assert recorder.rewrites.count(True) > 1, "the step was returned"


def pull_request_open(recorder: OnBranch) -> dict[str, Any]:
    recorder.store.set_state(UNIT, PLANNED, pr=7, branch=branch_name(unit()))
    return {}


def a_started_unit_on_the_branch(recorder: OnBranch) -> dict[str, Any]:
    above = stored_unit("above/1", change="above", depends_on=(UNIT,), state=IN_REVIEW, pr=9)
    recorder.store.upsert([above])
    return {"graph": [recorder.store.get(UNIT), recorder.store.get("above/1")]}


@pytest.mark.parametrize(
    ("hold", "named", "asked"),
    [
        pytest.param(pull_request_open, "pull request", False, id="open-pull-request"),
        pytest.param(a_started_unit_on_the_branch, "above/1", False, id="stacked-unit"),
        pytest.param(lambda recorder: {}, "", True, id="already-asked"),
    ],
)
def test_a_unit_the_check_may_not_ask_for_fails_as_before_with_no_request_and_the_command(
    tmp_path: Path,
    hold: Callable[[OnBranch], dict[str, Any]],
    named: str,
    asked: bool,
) -> None:
    recorder, repo = stale_group_12(tmp_path, asked=asked)
    build_options = hold(recorder)

    outcome = build(tmp_path, recorder, **build_options, **recorder.overrides(tmp_path))

    stored = recorder.store.get(UNIT)
    asks = [e for e in stored.history if e.get("event") == "rewrite_requested"]
    assert outcome.status == "failed"
    assert STOP_12 in outcome.detail
    assert SHAPE_COMMAND in outcome.detail
    assert named in outcome.detail
    assert stored.rewrite_request is None
    assert len(asks) == int(asked), "the check asked no more than it had"
    assert not any(recorder.rewrites), "no step that may rewrite ran"
    assert subjects(repo) == STALE_12


def test_a_shape_request_a_killed_step_left_stored_is_used_by_the_resumed_rework_not_left_stale(
    tmp_path: Path,
) -> None:
    recorder, _ = stale_group_12(tmp_path)
    recorder.store.set_rewrite_request(
        UNIT, StoredRewriteRequest(text="rewrite the group", source=RewriteSource.COMMIT_SHAPE)
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    stored = recorder.store.get(UNIT)
    assert outcome.status == "failed"
    assert SHAPE_COMMAND in outcome.detail
    assert stored.rewrite_request is None
    events = [e.get("event") for e in stored.history]
    assert "rewrite_used" in events, "the resumed rework step ended the request as used"
    assert recorder.rewrites[0], "the stored request ran a step that may rewrite, before the stop"
