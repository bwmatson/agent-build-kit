"""A person's note, given with `abk requeue --note`, reaches the agent ahead of whatever else
a rework hands it, and the review of the work that follows is told it too.

The six templates are checked as text, the guidance placed ahead of the feedback; a unit
with no guidance renders each one byte for byte as before. The node is driven through the
thread, with the agent faked, for the stored note: it is cleared by the rework commit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.rewrite_guard import UNCHANGED_REASON
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.stack_runner import (
    CHECKS_CONTINUATION,
    CHECKS_PROMPT,
    REVIEW_FEEDBACK_CONTINUATION,
    REVIEW_FEEDBACK_PROMPT,
    REWORK_CONTINUATION,
    REWORK_PROMPT,
    REWRITE_REQUEST_NOTE,
    WHOLE_ASK,
    RunOutcome,
    person_guidance,
)
from agent_build_kit.pipeline.unit_store import (
    FeedbackSource,
    RequeueReason,
    RewriteSource,
    StoredRewriteRequest,
)
from packages.worker.tests.graph.test_build_path import build
from packages.worker.tests.graph.test_session_continuation import Sessions, agents
from tests.factories import unit
from tests.graph.agent_fakes import distinct_models
from tests.graph.branch_fakes import (
    TRAILER,
    OnBranch,
    agent_calls,
    prepared,
    subjects,
    titled,
)
from tests.graph_driver import fresh, tick
from tests.runner_fakes import approving, rejecting

UNIT = unit().id
BUILT = "add-marker/1"  # the unit `tests.graph.branch_fakes.prepared` builds
NOTE = "give the date exactly as printed"
FEEDBACK = "FEEDBACK-TEXT"
FIELDS: dict[str, Any] = dict(
    change_dir="openspec/changes/feature",
    groups="1",
    feedback=FEEDBACK,
    boundary="",
    pr=7,
    changelog="",
)
# The first 16 hex digits of the SHA-256 of each template rendered with `FIELDS` and no guidance:
# as they were before guidance existed, then moved on purpose when the prompt's text changed: the
# note that the pipeline commits the work (`REWORK_PROMPT`, `REVIEW_FEEDBACK_PROMPT`), the output
# convention and the finish line's tests-by-file-or-id wording (every template here), and the
# local-server sentence (`CHECKS_PROMPT`, `CHECKS_CONTINUATION`), and the source version of the
# reuse guidance (the three full prompts), and the test standards' placement, scenario and fake
# rules (`REWORK_PROMPT`), and the note to write a `BLOCKED:` line for work whose prerequisite
# does not exist (`REWORK_PROMPT`, `REWORK_CONTINUATION`), and the test-edit rule (every template
# here: a test edit goes in the `test:` commit, and a test a fix round corrects goes in its `fix:`
# commit).
TEMPLATES = {
    "CHECKS_PROMPT": (CHECKS_PROMPT, "0fbbbbe9d9d956ee"),
    "CHECKS_CONTINUATION": (CHECKS_CONTINUATION, "5ec858ad153972e6"),
    "REWORK_PROMPT": (REWORK_PROMPT, "cea0112bbe9eaf3c"),
    "REWORK_CONTINUATION": (REWORK_CONTINUATION, "24ba2b74de85b0f7"),
    "REVIEW_FEEDBACK_PROMPT": (REVIEW_FEEDBACK_PROMPT, "6e539dbac35843b6"),
    "REVIEW_FEEDBACK_CONTINUATION": (REVIEW_FEEDBACK_CONTINUATION, "f6fc1f5e7a4863f4"),
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@pytest.mark.parametrize("name", TEMPLATES)
def test_a_template_shows_the_guidance_as_a_persons_instruction_ahead_of_the_feedback(
    name: str,
) -> None:
    template, before = TEMPLATES[name]

    with_note = template.format(**FIELDS, guidance=person_guidance(NOTE))
    without = template.format(**FIELDS, guidance=person_guidance(""))

    assert NOTE in with_note
    assert with_note.index(NOTE) < with_note.index(FEEDBACK)
    assert with_note.lower().count("person") > without.lower().count("person")
    assert digest(without) == before, "no guidance, no change to the text"


def requeue(guidance: str = NOTE) -> ResumeEvent:
    return ResumeEvent(
        kind=EventKind.REQUEUE,
        reason="requeue",
        requeue=RequeueReason.FROM_FAILURE,
        guidance=guidance,
    )


@pytest.mark.parametrize(
    "source", [FeedbackSource.UNIT_TEST, FeedbackSource.REVIEW], ids=["checks", "review"]
)
def test_a_reworked_unit_is_handed_the_note_ahead_of_its_saved_feedback(
    tmp_path: Path, source: FeedbackSource
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_feedback(UNIT, FEEDBACK, source=source)
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue())
    tick(tmp_path, recorder, run=agent)

    [prompt] = prompts
    assert prompt.index(NOTE) < prompt.index(FEEDBACK)


def test_the_rework_commit_clears_the_note_and_the_next_review_is_told_it(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_feedback(UNIT, FEEDBACK, source=FeedbackSource.REVIEW)
    reviews = len(recorder.contexts)
    held: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        held.append(recorder.store.get(UNIT).guidance)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue())
    tick(tmp_path, recorder, run=agent)

    assert held == [NOTE], "stored by the requeue, for the agent that runs"
    assert recorder.store.get(UNIT).guidance == "", "cleared where the rework commit is made"
    assert NOTE in "\n".join(recorder.contexts[reviews:]), "and the reviewer was told it"


def test_a_unit_with_only_a_note_and_no_saved_failure_is_reworked_from_the_note(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue())
    tick(tmp_path, recorder, run=agent)

    [prompt] = prompts
    assert prompt.startswith(person_guidance(NOTE) + "Review asked for a change")
    assert prompt.index(NOTE) < prompt.index(WHOLE_ASK)
    assert recorder.store.get(UNIT).guidance == ""


def test_a_unit_with_no_work_on_its_branch_builds_tests_first_with_the_note(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_guidance(UNIT, NOTE)

    tick(tmp_path, recorder)

    assert recorder.events[:2] == ["claude:tests", "commit:test"]
    assert NOTE in recorder.prompts[0]
    assert NOTE in recorder.prompts[1], "the implementation step is told it too"
    assert "claude:rework" not in recorder.events
    assert recorder.store.get(UNIT).guidance == "", "cleared by the implementation commit"
    assert NOTE in "\n".join(recorder.contexts), "and the review judges against it"


def test_a_note_given_to_the_review_loop_s_rework_is_told_to_the_next_review(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename the marker")]
    asked = False

    def review(**kwargs: Any) -> str:
        nonlocal asked
        if not asked:
            # The person's note arrives while the first round is out, so the rework it
            # asks for is the loop's, which the note is cleared in.
            asked = True
            recorder.store.set_guidance(UNIT, NOTE)
        return recorder.review(**kwargs)

    tick(tmp_path, recorder, run_review=review, run_rework_review=review)

    first, second = recorder.contexts
    assert NOTE not in first
    assert NOTE in second
    assert any(NOTE in prompt and "rename the marker" in prompt for prompt in recorder.prompts)
    assert recorder.store.get(UNIT).guidance == ""


ASKED = "squash the two fixup commits into the commit they repair"
NO_REWRITE = "Do not rewrite history"


def ask_for_rewrite(recorder: Any, source: RewriteSource = RewriteSource.PERSON) -> None:
    recorder.store.set_rewrite_request(UNIT, StoredRewriteRequest(text=ASKED, source=source))


def rework_prompts(tmp_path: Path, *, asking: bool) -> list[str]:
    """The prompts of a requeued rework, with a stored rewrite request when `asking`."""
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_feedback(UNIT, FEEDBACK, source=FeedbackSource.REVIEW)
    if asking:
        ask_for_rewrite(recorder)
    prompts: list[str] = []

    def agent(prompt: str, **kwargs: Any) -> str:
        prompts.append(prompt)
        return recorder.claude(prompt, **kwargs)

    tick(tmp_path, recorder, event=requeue(""))
    tick(tmp_path, recorder, run=agent)
    return prompts


def rework_prompt(tmp_path: Path, *, asking: bool) -> str:
    """The first prompt of a requeued rework."""
    return rework_prompts(tmp_path, asking=asking)[0]


def test_a_requeued_rework_with_a_stored_request_that_rewrites_nothing_is_returned_to_rewrite(
    tmp_path: Path,
) -> None:
    assert len(rework_prompts(tmp_path, asking=True)) > 1


def test_a_requeued_rework_with_a_stored_request_carries_it_and_allows_the_rewrite(
    tmp_path: Path,
) -> None:
    prompt = rework_prompt(tmp_path, asking=True)

    assert ASKED in prompt
    assert f"`Unit: {UNIT}`" in prompt
    assert NO_REWRITE not in prompt


def test_a_requeued_rework_with_no_stored_request_still_forbids_a_rewrite(
    tmp_path: Path,
) -> None:
    prompt = rework_prompt(tmp_path, asking=False)

    assert ASKED not in prompt
    assert NO_REWRITE in prompt


@pytest.mark.parametrize("asking", [True, False], ids=["request", "none"])
def test_the_review_loops_first_rework_prompt_carries_a_stored_request_only_when_there_is_one(
    tmp_path: Path, asking: bool
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename the marker")]
    asked = False

    def review(**kwargs: Any) -> str:
        nonlocal asked
        if not asked and asking:
            asked = True
            ask_for_rewrite(recorder, RewriteSource.REVIEW)
        return recorder.review(**kwargs)

    tick(tmp_path, recorder, run_review=review, run_rework_review=review)

    prompt = [p for p in recorder.prompts if "rename the marker" in p][0]
    assert (ASKED in prompt) is asking
    assert (NO_REWRITE in prompt) is not asking


def test_the_review_loops_rework_with_a_stored_request_that_rewrites_nothing_is_returned(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename the marker")]
    asked = False

    def review(**kwargs: Any) -> str:
        nonlocal asked
        if not asked:
            asked = True
            ask_for_rewrite(recorder, RewriteSource.REVIEW)
        return recorder.review(**kwargs)

    tick(tmp_path, recorder, run_review=review, run_rework_review=review)

    assert recorder.rewrites.count(True) > 1, "a rewrite that never came is returned"


STOPPED_AT_3 = ["test: G1", "feat: G1", "test: G2", "feat: G2", "wip: the third group"]


def rewrite_group_3(cwd: Path) -> None:
    """What a rework that honours the request does: the stray commit becomes group 3's pair."""
    git(cwd, "reset", "-q", "--hard", "HEAD~1")
    for index, subject in enumerate(("test: G3", "feat: G3")):
        (cwd / f"group-3-{index}.txt").write_text(f"{subject}\n")
        git(cwd, "add", "-A")
        git(cwd, "commit", "-q", "-m", f"{subject}\n\n{TRAILER}\nGroup: add-marker/3\n")


def stopped_at_group_3_with_a_request(
    tmp_path: Path, *, leaves_a_file: bool = False
) -> tuple[OnBranch, Path, RunOutcome]:
    """A unit of four groups whose branch holds groups 1 and 2, and a person's request; the
    fake rework rewrites group 3 into its pair, and leaves a file uncommitted when
    `leaves_a_file`."""
    recorder, repo = prepared(
        tmp_path, groups={"add-marker": titled(1, 2, 3, 4)}, seeded=STOPPED_AT_3
    )
    recorder.store.set_rewrite_request(
        BUILT, StoredRewriteRequest(text=ASKED, source=RewriteSource.PERSON)
    )
    original = recorder.claude

    def claude(prompt: str, **kwargs: Any) -> str:
        if not kwargs.get("rewrite"):
            return original(prompt, **kwargs)
        recorder.prompts.append(prompt)
        recorder.rewrites.append(True)
        rewrite_group_3(kwargs["cwd"])
        if leaves_a_file:
            (kwargs["cwd"] / "left-over.txt").write_text("not committed\n")
        return "done"

    recorder.claude = claude
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))
    return recorder, repo, outcome


def test_a_unit_stopped_mid_build_with_a_request_goes_to_the_rework_not_the_groups_steps(
    tmp_path: Path,
) -> None:
    recorder, _, _ = stopped_at_group_3_with_a_request(tmp_path)

    assert recorder.rewrites[0] is True
    assert ASKED in recorder.prompts[0]
    assert recorder.prompts[0] != recorder.prompts[1], "the first run is not group 3's tests step"
    assert "test tasks" not in recorder.prompts[0]


def test_a_rewrite_of_the_stopped_group_clears_the_request_and_the_build_goes_on_at_group_4(
    tmp_path: Path,
) -> None:
    recorder, repo, outcome = stopped_at_group_3_with_a_request(tmp_path)

    stored = recorder.store.get(BUILT)
    assert outcome.status != "failed"
    assert stored.rewrite_request is None
    assert "history_rewritten" in str(stored.history)
    assert agent_calls(recorder.events) == ["claude:tests", "claude:impl"], "only group 4 is built"
    assert subjects(repo)[:6] == [
        "test: G1",
        "feat: G1",
        "test: G2",
        "feat: G2",
        "test: G3",
        "feat: G3",
    ]


def test_a_file_the_rewrite_left_uncommitted_is_not_committed_as_a_fix_between_the_groups(
    tmp_path: Path,
) -> None:
    _, repo, _ = stopped_at_group_3_with_a_request(tmp_path, leaves_a_file=True)

    assert not any(s.startswith("fix:") for s in subjects(repo))
    assert subjects(repo)[4:6] == ["test: G3", "feat: G3"]


def test_the_tests_and_implement_steps_never_get_the_rewrite_policy(tmp_path: Path) -> None:
    recorder, _, _ = stopped_at_group_3_with_a_request(tmp_path)

    assert recorder.rewrites[0] is True
    assert recorder.rewrites[1:] and not any(recorder.rewrites[1:])


def test_a_continued_session_is_told_the_request_and_then_the_guards_reason_in_its_follow_up(
    tmp_path: Path,
) -> None:
    """The review loop's rework continues the author's session, which never sees the full
    prompt: the request goes in the follow-up, and so does the reason the guard returned the
    step for (the fake worktree's head never moves, so the step is returned)."""
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions(verdicts=[rejecting("rename the marker"), approving()])
    runs = agents(runtime)
    asked = False

    def review(**kwargs: Any) -> str:
        nonlocal asked
        if not asked:
            asked = True
            ask_for_rewrite(recorder, RewriteSource.REVIEW)
        return runs["run_review"](**kwargs)

    tick(
        tmp_path,
        recorder,
        run=runs["run"],
        run_review=review,
        run_rework_review=runs["run_rework_review"],
    )

    _, _, first, *returned = runtime.built
    assert first.resume_session == "sess-1", "the rework continues the author's session"
    assert ASKED in first.prompt
    assert returned, "the guard returned the step"
    assert all(r.resume_session == "sess-1" for r in returned)
    assert all(UNCHANGED_REASON in r.prompt for r in returned)
    assert UNCHANGED_REASON not in first.prompt


def test_the_note_given_with_a_rewrite_request_says_the_pipeline_publishes_the_branch() -> None:
    note = REWRITE_REQUEST_NOTE.format(request=ASKED, base="origin/main", unit=UNIT)

    assert "Do not push." not in note, "it is not only a ban: the agent is told who pushes"
    assert "pipeline" in note and "publish" in note
    assert all(command in note for command in ("commit", "reset", "rebase"))


def test_the_head_the_rework_began_on_is_kept_and_named_in_the_history(tmp_path: Path) -> None:
    recorder, repo, _ = stopped_at_group_3_with_a_request(tmp_path)

    kept = git_out(repo, "for-each-ref", "--format=%(refname)", "refs/abk/before-rewrite/").split()
    assert len(kept) == 1
    assert kept[0] in str(recorder.store.get(BUILT).history)
    assert git_out(repo, "log", "-1", "--format=%s", kept[0]) == "wip: the third group"
