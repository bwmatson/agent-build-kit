"""A stored build session that `claude` cannot find under a changed account is run afresh
(spec: usage-account, design: a stored session of another account is already handled).

The unit is not failed: the node runs from its start in a new session, and the line says the
session cannot be continued and names the account directory; with no account set the line is
as it was.
"""

from pathlib import Path

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.settings import settings
from tests.graph.test_agent_session import Sessions, killed_in_the_tests_step, logged, run_log
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Killed

GONE = "No conversation found with session ID: sess-1"


def resumed_under(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, account: Path | None) -> str:
    """The unit's log after its node, killed in session `sess-1`, is resumed where `claude`
    answers that no conversation is found."""
    tmp_path.mkdir()
    monkeypatch.setattr(settings, "claude_home", account)
    runtime = Sessions(refuses=GONE)
    recorder = killed_in_the_tests_step(tmp_path, runtime)

    outcome = tick(tmp_path, recorder, run=build_run(runtime=runtime), run_log=run_log(tmp_path))

    assert outcome.status == RunStatus.OPEN
    killed, refused, fresh_start, *_ = runtime.requests
    assert refused.resume_session == "sess-1"
    assert fresh_start.resume_session == ""
    assert fresh_start.prompt == killed.prompt
    return logged(tmp_path)


def test_a_session_of_another_account_runs_afresh_and_the_line_names_the_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = tmp_path / "account"
    default = resumed_under(monkeypatch, tmp_path / "default", None)

    line = resumed_under(monkeypatch, tmp_path / "set", account)

    assert "cannot be continued" in line
    assert "new session" in line
    assert str(account) in line
    assert str(account) not in default
    assert "cannot be continued" in default


def test_the_line_names_the_account_of_a_labelled_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.mkdir(exist_ok=True)
    kit = tmp_path / "kit-home"
    monkeypatch.setattr(settings, "claude_home", tmp_path / "default-home")
    runtime = Sessions(refuses=GONE)
    account = Account(label="kit", config_dir=kit)
    recorder = fresh(tmp_path)
    with pytest.raises(Killed):
        tick(tmp_path, recorder, run=build_run(runtime=runtime), account=account)

    tick(
        tmp_path,
        recorder,
        run=build_run(runtime=runtime),
        run_log=run_log(tmp_path),
        account=account,
    )

    line = logged(tmp_path)
    assert f"under the account {kit}" in line
    assert "default-home" not in line
