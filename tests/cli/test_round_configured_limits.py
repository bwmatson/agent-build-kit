"""A round with nothing to start is judged on the installation's configured Claude limits
(spec: usage-pause, claude-account).

With no unit that could start and no planning due, the round's start decision still names an
account to judge. It is the default account as the installation resolves it, with the configured
limits, never one carrying the stock thresholds. The real guard runs; only the endpoint is faked
(`tests/usage_host.py`).
"""

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.vanished_fakes import keep_changes_of_unstarted_units
from tests.conftest import make_installation
from tests.usage_host import Host, payload

# The stock session threshold is 70; the installation raises it above the reading.
CONFIGURED_PAUSE_PCT = 95
READING_PCT = 85.0


@pytest.fixture
def inst(tmp_path: Path, host: Host) -> Installation:
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        runtimes={
            "claude_code": {"usage_limits": {"session": {"usage_pause_pct": CONFIGURED_PAUSE_PCT}}}
        },
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    return inst


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    keep_changes_of_unstarted_units(monkeypatch)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)


def test_a_round_with_nothing_to_start_follows_the_configured_threshold(
    inst: Installation, host: Host
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    host.answers = [payload(session=READING_PCT)]

    started = cli.run_round(
        inst, store, building=set(), started=set(), only=frozenset(), submit=True
    )

    assert started == []
    assert host.asked == 1, "the guard was asked, so the decision was made"
    assert is_paused(inst.state_dir / "paused.json") is None, (
        f"a session reading of {READING_PCT}% is under the configured {CONFIGURED_PAUSE_PCT}%"
    )
