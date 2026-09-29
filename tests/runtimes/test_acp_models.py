"""How the `acp` adapter chooses a model: selected, never demanded.

An agent advertises the models it offers as a session config option in the
`model` category, and a client picks among them. So a role's model is chosen
when the agent offers it, and when it does not the run carries on with the
agent's own default — reporting that once, not once per unit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.runtimes.acp_agent import ANSWER, DEFAULT_MODEL, MODEL_AT_PROMPT, requests, use_agent


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path / "worktree"
    path.mkdir()
    return path


def _request(worktree: Path, model: str | None) -> AgentRequest:
    return AgentRequest(prompt="Review the branch.", role="review", cwd=worktree, model=model)


def test_an_offered_model_is_selected_for_the_session(tmp_path: Path, worktree: Path) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record)

    result = AcpRuntime().run(_request(worktree, "deep-2"))

    assert result.ok is True
    [session] = requests(record, "session/new")
    assert session["cwd"] == str(worktree)
    chosen = requests(record, "session/set_config_option")
    assert [(c["configId"], c["value"]) for c in chosen] == [("model", "deep-2")]
    [at_prompt] = requests(record, MODEL_AT_PROMPT)
    assert at_prompt["model"] == "deep-2"


def test_a_model_the_agent_does_not_offer_runs_on_its_default(
    tmp_path: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not a failure: a name the agent does not know is a no-op in the
    protocol, so the unit is built on the agent's default rather than held."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)

    result = AcpRuntime().run(_request(worktree, "opus"))

    assert result.ok is True
    assert result.text == ANSWER
    assert not any(c["value"] == "opus" for c in requests(record, "session/set_config_option"))
    [at_prompt] = requests(record, MODEL_AT_PROMPT)
    assert at_prompt["model"] == DEFAULT_MODEL
    assert "opus" in capsys.readouterr().err


def test_the_mismatch_is_reported_once_not_once_per_run(
    tmp_path: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tick runs many units through the same runtime; one line saying the
    configured model is not on offer is news, the same line per unit is noise."""
    use_agent(tmp_path / "agent.jsonl")
    runtime = AcpRuntime()

    runtime.run(_request(worktree, "opus"))
    runtime.run(_request(worktree, "opus"))

    reports = [line for line in capsys.readouterr().err.splitlines() if "opus" in line]
    assert len(reports) == 1, reports


def test_default_models_are_this_runtime_s_own_not_claude_code_s() -> None:
    """A runtime's `default_models` is what a role resolves to once nothing
    in abk.yaml or the environment names one (`config.models()`) — never
    another runtime's names, and acp has no default agent of its own to name
    one for."""
    defaults = AcpRuntime().default_models
    assert defaults.implement == ""
    assert defaults.rework == ""
    assert defaults.review == ""
    assert defaults.rework_review == ""


def test_no_model_named_sends_no_selection_and_reports_nothing(
    tmp_path: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`ModelsConfig.pick` falls back to this on an unconfigured workspace, so
    an empty name must be silent, not a report of a model the agent does not
    offer once per run."""
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    lines: list[str] = []

    result = AcpRuntime().run(_request(worktree, "").model_copy(update={"on_event": lines.append}))

    assert result.ok is True
    assert requests(record, "session/set_config_option") == []
    assert capsys.readouterr().err == ""
    assert not any("model" in line.lower() for line in lines)
