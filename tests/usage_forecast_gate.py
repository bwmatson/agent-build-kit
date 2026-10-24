"""State for the start decision's forecast: a history laid beside the guard's cache file, a kept
calibration of 2.5 points a dollar, and a reading held (decided on an estimate) or live."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.pipeline.usage_guard import Decision, decide_start, starting
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, append_record
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.usage_cost_estimate import OBSERVED_AGE, cost_fit, keep_fits
from tests.usage_forecast_fixtures import Fixture, call
from tests.usage_host import Host, configure, payload, refused

MINUTE = timedelta(minutes=1)
# A quantile of one half adds nothing to a chance and six calls are enough for a cell's own mean,
# so the scenarios' arithmetic is exact.
EXACT = {"usage_forecast_quantile": 0.5, "usage_forecast_min_runs": 6}


def lay(host: Host, history: Fixture) -> None:
    """The ledger rows and verdict records of `history`, in the state directory."""
    state = host.cache.parent
    state.mkdir(parents=True, exist_ok=True)
    for record in history.records:
        append_record(state / LEDGER_NAME, record)
    (state / VERDICTS).write_text(
        json.dumps(
            {
                unit: entry.model_dump(mode="json", exclude={"split"})
                for unit, entry in history.verdicts.items()
            }
        )
    )


def lay_calls(host: Host, node: str, usd: float, *, unit: str = "", times: int = 2) -> None:
    """`times` ledger rows of `node` costing `usd` dollars, well before any reading."""
    for n in range(times):
        append_record(host.cache.parent / LEDGER_NAME, call(unit or f"{node}-{n}", node, 0, usd))


def keep_points(host: Host, session: float = 2.5, weekly: float = 2.5) -> None:
    """The kept calibration: `session` and `weekly` points a dollar."""
    keep_fits(host, session=cost_fit(session), weekly=cost_fit(weekly))


def held(
    host: Host,
    *,
    session: float,
    weekly: float = 6.0,
    session_pause: int = 80,
    weekly_pause: int = 80,
    **limits: object,
) -> None:
    """A reading just under an hour old, the endpoint refusing and a climb fast enough that the
    reading alone leaves no headroom, so a start is decided on an estimate."""
    configure(
        session={"usage_pause_pct": session_pause},
        weekly={"usage_pause_pct": weekly_pause},
        **{"usage_climb_floor": 2.0, **EXACT, **limits},
    )
    host.keep_reading(OBSERVED_AGE, payload(session=session, weekly=weekly))
    refused(host, cooling=3 * MINUTE)
    keep_points(host)


def live(host: Host, *, session: float, weekly: float = 6.0, **limits: object) -> None:
    """A reading the endpoint gives when asked, thresholds of 80."""
    configure(
        session={"usage_pause_pct": 80}, weekly={"usage_pause_pct": 80}, **{**EXACT, **limits}
    )
    host.answers = [payload(session=session, weekly=weekly)]
    keep_points(host)


def keep_timer(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, track: str, fires_in: timedelta
) -> None:
    """A `systemctl` that shows the installed timer of `track` (`health`) elapsing `fires_in`
    from now and no other timer, in the form the real one prints; the active installation has a
    root, which is where the timers are looked for, and the state directory is the host's."""
    elapse = (datetime.now(UTC) + fires_in).strftime("%a %Y-%m-%d %H:%M:%S UTC")
    program = tmp_path / "bin" / "systemctl"
    program.parent.mkdir()
    program.write_text(
        "#!/bin/sh\n"
        f'case "$3" in *track-{track}*)\n'
        "  printf 'LoadState=loaded\\n"
        f"NextElapseUSecRealtime={elapse}\\nLastTriggerUSec=n/a\\n' ;;\n"
        "*) printf 'LoadState=not-found\\n' ;;\n"
        "esac\n"
    )
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{program.parent}{os.pathsep}{os.environ['PATH']}")
    config = config_module.active()
    state = config.planning.model_copy(update={"state_dir": str(host.cache.parent)})
    config_module.activate(config.model_copy(update={"planning": state}), tmp_path / "planning")


def ask(
    tier: ReviewTier | None,
    unit: str = "feature/1",
    *,
    step: str | None = None,
    step_round: int | None = None,
) -> Decision:
    """The decision for `unit` of review tier `tier` asking to start, the way a gate asks."""
    with starting(unit, review_tier=tier, estimated_lines=10):
        return decide_start(step=step, step_round=step_round)
