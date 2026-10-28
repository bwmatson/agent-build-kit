"""The planner's graph call carries the role `plan` and the model that role resolves to, so
`--model opus` reaches `claude`, and its ledger row names both (spec: planner-model, the planner
has a model role)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planner import build_prompt, plan_round
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.settings import settings
from tests.pipeline.test_planner_runtime import CHANGES, IN_FLIGHT, PLAN
from tests.runtimes.claude_cli import MODEL, FakeClaude, finished_build
from tests.runtimes.stand_in import StandInRuntime
from tests.runtimes.test_claude_code_argv import flags


def test_the_planner_s_request_has_the_role_plan_and_the_resolved_model() -> None:
    runtime = StandInRuntime(answer=json.dumps(PLAN))

    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=runtime)

    assert runtime.request.role == "plan"
    assert runtime.request.model == config.models().plan == "opus"


def test_the_default_sends_model_opus_to_claude(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, json.dumps(PLAN)))

    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=ClaudeCodeRuntime(execute=fake))

    assert flags(fake.argv, build_prompt(CHANGES, IN_FLIGHT))["--model"] == "opus"


def test_a_model_named_for_the_role_replaces_it(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("version: 1\nruntimes:\n  claude_code:\n    models:\n      plan: sonnet\n")
    config.activate(config.load(path), tmp_path)
    runtime = StandInRuntime(answer=json.dumps(PLAN))

    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=runtime)

    assert runtime.request.model == "sonnet"


def test_the_machine_setting_reaches_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "plan_model", "haiku")
    runtime = StandInRuntime(answer=json.dumps(PLAN))

    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=runtime)

    assert runtime.request.model == "haiku"


def test_the_ledger_row_of_a_plan_call_names_the_role_the_model_and_the_reported_model(
    workspace: Installation, tmp_path: Path
) -> None:
    fake = FakeClaude(stdout=finished_build(tmp_path, json.dumps(PLAN)))

    plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=ClaudeCodeRuntime(execute=fake))

    (row,) = [r for r in read_ledger(workspace.state_dir / LEDGER_NAME) if r.node == "plan"]
    assert row.role == "plan"
    assert row.model == "opus"
    assert row.reported_model == MODEL
