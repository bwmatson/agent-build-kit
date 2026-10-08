"""Every agent node reaches its agent through one `run`, which takes the model for the
call (docs/agent-runtimes.md): the build nodes and the fix of failing checks on the
implement model, the ones that rework on the rework model."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.config import models
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.wiring import build_commit
from tests.factories import init_repo
from tests.graph.agent_fakes import MODELS, Runs, distinct_models
from tests.graph.test_build_path import FAILING, build, once, restacked
from tests.graph_driver import fresh, tick
from tests.runner_fakes import rejecting

FEEDBACK = "[comment c1] src/app.py:3 — remove this line"


def test_tests_and_implement_run_on_the_implement_model(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runs = Runs(recorder)

    tick(tmp_path, recorder, run=runs)

    tests, implement = runs.calls
    assert (tests.model, implement.model) == (MODELS.implement, MODELS.implement)
    assert "test tasks" in tests.prompt, "the tests prompt"
    assert "test tasks" not in implement.prompt, "the implementation prompt"
    assert tests.cwd == implement.cwd == tmp_path / "tree"


def test_fix_checks_runs_on_the_implement_model_with_the_failing_output(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, FAILING), (True, "")]
    runs = Runs(recorder)

    tick(tmp_path, recorder, run=runs)

    *_, fix = runs.calls
    assert len(runs.calls) == 3, "the tests, the implementation, the fix"
    assert fix.model == MODELS.implement
    assert FAILING in fix.prompt
    assert fix.cwd == tmp_path / "tree"


def test_rework_continues_the_build_session_on_its_model_with_the_feedback(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder, run=Runs(recorder))
    event = ResumeEvent(
        kind=EventKind.REWORK, reason="comment", feedback=FEEDBACK, from_person=True
    )
    tick(tmp_path, recorder, run=Runs(recorder), event=event)
    runs = Runs(recorder)

    tick(tmp_path, recorder, run=runs)

    (rework,) = runs.calls
    assert rework.model == MODELS.implement, "the model the session began on"
    assert FEEDBACK in rework.prompt
    assert rework.cwd == tmp_path / "tree"


def test_adapt_runs_on_the_rework_model_with_the_predecessor_named(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runs = Runs(recorder)

    build(
        tmp_path,
        recorder,
        base="spec/c/2",
        run=runs,
        branch_commits=lambda cwd, base: 2 + recorder.made,
        restack_onto=once(restacked(conflict="x", old_tests=())),
        reset_to=lambda tree, onto, keep: None,
        tests_in=lambda tree: set(),
        tests_changed=lambda tree, ref: set(),
    )

    adapt = runs.calls[0]
    assert adapt.model == MODELS.rework
    assert "c/2" in adapt.prompt
    assert adapt.cwd == tmp_path / "tree"


def test_a_rework_after_a_rejecting_review_continues_on_the_sessions_model_with_the_findings(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the session registry leaks")]
    runs = Runs(recorder)

    tick(tmp_path, recorder, run=runs)

    *_, rework = runs.calls
    assert len(runs.calls) == 3, "the tests, the implementation, the rework"
    assert rework.model == MODELS.implement, "the model the session began on"
    assert "the session registry leaks" in rework.prompt
    assert rework.cwd == tmp_path / "tree"


class Fixer:
    """The agent a rejected commit goes back to: what it was called with."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, str]] = []

    def __call__(self, prompt: str, *, cwd: Path, model: str) -> str:
        self.calls.append((prompt, cwd, model))
        (cwd / "marker.py").write_text("x = 1\n")
        return "done"


GATE = """\
#!/bin/sh
grep -q 'x = 1' marker.py || (echo 'gate: wrong'; exit 1)
"""


def test_a_rejected_commit_goes_back_through_run_on_the_implement_model(tmp_path: Path) -> None:
    distinct_models()
    repo = init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    gate = repo / ".git" / "hooks" / "pre-commit"
    gate.write_text(GATE)
    gate.chmod(0o755)
    (repo / "marker.py").write_text("x = 2\n")
    fixer = Fixer()

    made = build_commit(unit_id="add-marker/1", fix=fixer)("test: covers it", cwd=repo)

    assert made == 1
    ((prompt, cwd, model),) = fixer.calls
    assert "gate: wrong" in prompt
    assert cwd == repo
    assert model == models().implement == MODELS.implement
