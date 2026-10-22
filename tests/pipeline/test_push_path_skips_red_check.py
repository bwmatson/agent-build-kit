"""The runner's push path and the build nodes never run the gate's red check, so a green real
`test:` followed by an empty `feat:` does not stop a push (spec:
built-group-recorded-as-empty-pair). Only `abk gate` calls `check_branch`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import agent_build_kit
from agent_build_kit.pipeline import gate
from tests.graph.branch_fakes import built, subjects, titled

SRC = Path(agent_build_kit.__file__).parent
CALL = re.compile(r"\bcheck_branch\(")


def test_only_the_gate_command_calls_check_branch_so_a_real_test_and_an_empty_feat_can_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    callers = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if CALL.search(path.read_text())
    }
    assert callers == {"pipeline/gate.py", "cli/pipeline.py"}

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the push path ran the gate's red check")

    monkeypatch.setattr(gate, "check_branch", forbidden)

    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": titled(1, 2)}, no_commit_for="2"
    )

    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == ["test: G1", "feat: G1", "test: G2", "feat: G2"]
    assert recorder.events.count("unit-test:whole_repo") == 1
