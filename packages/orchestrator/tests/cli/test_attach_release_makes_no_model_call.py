"""`abk attach release --commit` builds its subject, makes its commit and reports the gate's
rejection without calling a model (spec: attach-commit-subject). The registered runtime is a
stand-in whose every call fails the test."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config, runtimes
from agent_build_kit.cli import main
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from tests.factories import git
from tests.stubbed_attach import (
    TITLE,
    UNIT,
    dirty_tree,
    last_subject,
    stubbed_installation,
)


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = stubbed_installation(tmp_path)
    monkeypatch.chdir(installation.root)
    return installation


@pytest.fixture(autouse=True)
def no_model(monkeypatch: pytest.MonkeyPatch, inst: Installation) -> None:
    def refused(*args: object, **kwargs: object) -> None:
        pytest.fail("the release called a model")

    monkeypatch.setattr(runtimes.get(config.runtime_name()), "run", refused)


def test_the_commit_is_made_with_the_computed_subject_when_every_model_call_is_refused(
    inst: Installation,
) -> None:
    tree = dirty_tree(inst, f"test: {TITLE}")

    assert main(["attach", "release", UNIT, "--commit", "no model needed"]) == 0

    assert last_subject(tree) == f"feat: {TITLE}"


def test_a_gate_rejection_is_reported_with_the_gates_output_and_starts_no_agent(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    tree = dirty_tree(inst, f"test: {TITLE}")
    hooks = Path(git(tree, "rev-parse", "--git-common-dir").strip()).resolve() / "hooks"
    hooks.mkdir(exist_ok=True)
    hook = hooks / "commit-msg"
    hook.write_text('#!/bin/sh\necho "gate: rejected $(head -1 "$1")" >&2\nexit 1\n')
    hook.chmod(0o755)

    assert main(["attach", "release", UNIT, "--commit", "try"]) == 1

    assert f"gate: rejected feat: {TITLE}" in capsys.readouterr().out
    assert sorted(git(tree, "diff", "HEAD", "--name-only").split()) == ["base.txt", "new.py"]
    kept = Leases(lease_dir(inst.state_dir)).attachment(UNIT)
    assert kept is not None and kept.changed == 2, "the lease is kept"
