"""What the policy step records is part of init's commit: it runs before the agent steps."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from tests.cli.init_choice_fakes import Answers, Offering, answering, machine
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.factories import git, recognised_planning


def test_a_declined_token_spending_check_is_recorded_in_the_commit_and_leaves_the_tree_clean(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = Offering("alpha", events=events)
    runtime.policy_check_prompts_agent = True
    machine(monkeypatch, ("alpha-bin",), runtime, events=events)
    answering(monkeypatch, Answers(by_keyword={"token": "n"}))
    planning = recognised_planning(tmp_path / "planning")

    assert main(init_args(planning, app)) == 0

    raw = yaml.safe_load((planning / "abk.yaml").read_text())
    assert raw["runtimes"]["alpha"]["policy"] == "unchecked"
    assert "abk init: workspace" in git(planning, "log", "--oneline")
    assert git(planning, "status", "--porcelain") == ""
