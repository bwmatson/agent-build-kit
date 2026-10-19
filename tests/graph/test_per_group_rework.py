"""A unit built per group is reworked as any finished branch is: its `fix:` commits come after the
last pair, review sees the whole branch, and the pairs already built are not written again when
it is requeued with review feedback (spec: per-group-commits)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import activate_with, git, stored_unit
from tests.graph.branch_fakes import BASE, UNIT, OnBranch, messages, subjects, write_tasks
from tests.graph.test_outside_commits_prompt import branch
from tests.graph_driver import fresh, tick
from tests.runner_fakes import rejecting

ASK = ResumeEvent(
    kind=EventKind.REWORK,
    reason="comment",
    feedback="[comment n1] src/app.py:3 — rename it",
    from_person=True,
    comment_ids=("n1",),
)
GROUPS = {n: (f"G{n}", f"Done when group {n} is built.") for n in (1, 2, 3)}
PAIRS = ["test: G1", "feat: G1", "test: G2", "feat: G2", "test: G3", "feat: G3"]


def test_review_feedback_adds_fix_commits_after_the_last_pair_and_writes_no_pair_again(
    tmp_path: Path,
) -> None:
    activate_with(builders={"per_group_commits": True})
    write_tasks(tmp_path, "add-marker", GROUPS)
    repo = branch(tmp_path)
    plain = fresh(tmp_path)
    plain.store.upsert([stored_unit(groups=(1, 2, 3))])
    recorder = OnBranch(plain.store)
    overrides = recorder.overrides(tmp_path)
    subject = recorder.store.get(UNIT)

    tick(tmp_path, recorder, subject=subject, **overrides)
    assert recorder.store.get(UNIT).state == IN_REVIEW
    built = git(repo, "rev-list", "--reverse", f"{BASE}..HEAD").split()
    assert subjects(repo) == PAIRS
    for index, message in enumerate(messages(repo)):
        assert f"Done when group {index // 2 + 1} is built." in message

    recorder.verdicts = [rejecting("The marker is not tested when empty.")]
    tick(tmp_path, recorder, subject=subject, event=ASK, **overrides)
    tick(tmp_path, recorder, subject=subject, **overrides)

    assert git(repo, "rev-list", "--reverse", f"{BASE}..HEAD").split()[:6] == built
    assert subjects(repo)[:6] == PAIRS
    assert all(s.startswith("fix: ") for s in subjects(repo)[6:]) and len(subjects(repo)) > 6
    assert recorder.events.count("claude:tests") == 3
    assert recorder.events.count("claude:impl") == 3
    assert recorder.events.count("claude:rework") >= 1
    assert recorder.events.count("review") >= 2, "the reworked branch is reviewed again"
