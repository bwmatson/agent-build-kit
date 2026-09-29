"""What happens when Anthropic refuses the call outright.

`usage_guard` gates *starting* a unit, which is a prediction: it reads the
window before the work and assumes the work fits. A hard rate limit is the
case where that prediction was wrong, and it arrives mid-run.

Two things must be true, or an unattended pipeline makes it worse:

- **It is a pause, not a failure.** The unit is fine; the account is out of
  room. Marking it failed would take real work out of the plan for a reason
  that has nothing to do with it.
- **There is no retry loop.** Retrying a refusal costs a call to be told the
  same thing, and a five-minute timer would do it all night.
"""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.usage_guard import RateLimited, rate_limit_reset
from agent_build_kit.pipeline.wiring import build_run_claude


@pytest.mark.parametrize(
    "text",
    [
        "Claude AI usage limit reached|1919763200",
        "Error: rate limit exceeded",
        "API Error: 429 rate_limit_error",
        "5-hour limit reached ∙ resets 3am",
    ],
)
def test_the_shapes_a_refusal_arrives_in_are_recognised(text: str) -> None:
    """Detection is on the message, which is not a contract — so it matches
    several phrasings rather than one, and errs toward pausing."""
    assert rate_limit_reset(text) is not False


def test_an_ordinary_failure_is_not_mistaken_for_one() -> None:
    """Pausing on every error would stop the pipeline for a syntax error."""
    assert rate_limit_reset("error: could not resolve host github.com") is False


def test_a_reset_timestamp_in_the_message_is_used() -> None:
    """When the refusal says when it lifts, that beats anything inferred."""
    when = rate_limit_reset("Claude AI usage limit reached|1919763200")

    assert isinstance(when, datetime)
    assert when.year == 2030


def test_a_refusal_with_no_timestamp_still_pauses() -> None:
    """The live usage reading supplies the time instead; what matters here is
    that the absence of one does not read as "not rate limited"."""
    assert rate_limit_reset("Error: rate limit exceeded") is None


def test_the_error_carries_the_reset_time_for_the_pause() -> None:
    when = datetime.now(UTC) + timedelta(hours=2)

    error = RateLimited("usage limit reached", resets_at=when)

    assert error.resets_at == when


def refusal(**kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        ["claude"], 1, "", "Claude AI usage limit reached|1919763200"
    )


def test_a_refused_run_raises_rather_than_returning_nothing(tmp_path: Path) -> None:
    """It used to return empty stdout and carry on: the commit step then found
    nothing staged, and the unit was recorded as the model having produced
    nothing. The account being out of room is not that."""
    with pytest.raises(RateLimited):
        build_run_claude(run=lambda *a, **k: refusal())("do the thing", cwd=tmp_path)


def test_an_ordinary_failure_also_stops_the_run(tmp_path: Path) -> None:
    """Half-finished edits are on disk; carrying on would commit them as a
    finished unit and put them in front of a reviewer."""
    broken = subprocess.CompletedProcess(["claude"], 1, "", "error: something broke")

    with pytest.raises(RuntimeError) as caught:
        build_run_claude(run=lambda *a, **k: broken)("do the thing", cwd=tmp_path)

    assert not isinstance(caught.value, RateLimited)


def test_a_streamed_transcript_that_mentions_rate_limits_is_not_a_refusal(
    tmp_path: Path,
) -> None:
    """A build's stream carries uuids, the files it read and its own prose;
    only the result event and stderr say whether the account refused."""
    transcript = "\n".join(
        json.dumps(event)
        for event in (
            {"type": "system", "subtype": "init", "session_id": "7c2e4290-1d5a-4b8f"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "rate limit"}]}},
            {
                "type": "result",
                "subtype": "error_during_execution",
                "is_error": True,
                "errors": ["Execution error"],
            },
        )
    )
    broken = subprocess.CompletedProcess(["claude"], 1, transcript, "")

    with pytest.raises(RuntimeError) as caught:
        build_run_claude(run=lambda *a, **k: broken)("do the thing", cwd=tmp_path)

    assert not isinstance(caught.value, RateLimited)
    assert str(caught.value) == "claude exited 1: Execution error"


def test_a_refusal_reported_in_the_result_s_errors_is_a_refusal(tmp_path: Path) -> None:
    """An error-subtype result has no `result` text; what went wrong is in
    its `errors`."""
    transcript = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "errors": ['API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}'],
        }
    )
    refused = subprocess.CompletedProcess(["claude"], 1, transcript, "")

    with pytest.raises(RateLimited):
        build_run_claude(run=lambda *a, **k: refused)("do the thing", cwd=tmp_path)


def test_a_successful_run_is_unaffected(tmp_path: Path) -> None:
    ok = subprocess.CompletedProcess(["claude"], 0, "did the thing", "")

    assert build_run_claude(run=lambda *a, **k: ok)("do the thing", cwd=tmp_path) == "did the thing"


def test_being_refused_pauses_the_tick_rather_than_failing_the_unit(
    tmp_path: Path, monkeypatch
) -> None:
    """The unit is fine — the account is out of room. Marking it failed would
    drop real work from the plan for a reason that has nothing to do with it."""
    from agent_build_kit.cli import pipeline as cli
    from agent_build_kit.pipeline import pause
    from tests.conftest import make_installation

    inst = make_installation(tmp_path, planning={"state_dir": "."})
    monkeypatch.setattr(pause, "systemd_resume", lambda seconds, command, **k: None)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([Unit(id="c/1", change="c", title="A", repo="app", tier="tier1", groups=(1,))])

    when = datetime.now(UTC) + timedelta(hours=2)

    class Refusing:
        def run(self, unit, *, base, graph):
            raise RateLimited("usage limit reached", resets_at=when)

    monkeypatch.setattr(cli, "build_runner", lambda unit, **kw: Refusing())

    keep_going = cli._build(inst, store.get("c/1"), store=store, graph=store.all())

    assert keep_going is False, "no retry loop: the rest of the round is abandoned"
    assert store.get("c/1").state != "failed"
    assert (tmp_path / "paused.json").exists()


def test_a_claude_killed_by_a_signal_is_interrupted(tmp_path: Path) -> None:
    from agent_build_kit.pipeline.usage_guard import Interrupted

    killed = subprocess.CompletedProcess(["claude"], -9, '{"type":"system"}', "")

    with pytest.raises(Interrupted, match="signal 9"):
        build_run_claude(run=lambda *a, **k: killed)("do the thing", cwd=tmp_path)
