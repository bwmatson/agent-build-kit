# ruff: noqa: F811 — the imported fixture is requested by name
"""The round's own ask of the guard names no unit, so an allowance on an estimate is never kept
under a unit that does not run on the account (spec: usage-pause-slots, starting a unit and the
gate ask one question).

`app` runs on the default account, whose reading is over its threshold, and `platform` on
`personal`, whose reading is old enough that a start is decided on an estimate. The cheapest
unit is `app`'s.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit import claude_account
from agent_build_kit.pipeline.usage_calls import calls_path
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.cli.test_admission_asks_own_account import (  # noqa: F401
    PERSONAL,
    isolated,
    round_of,
    unit,
    workspace,
)
from tests.usage_host import Host, payload

MINUTE = timedelta(minutes=1)


def test_the_rounds_ask_keeps_no_unit_on_an_account_it_does_not_run_on(
    tmp_path: Path, host: Host
) -> None:
    cheap = unit("one/1", "app").model_copy(update={"review_tier": ReviewTier.AUTO.value})
    dear = unit("two/1", "platform").model_copy(update={"review_tier": ReviewTier.FULL.value})
    inst, store = workspace(tmp_path, [cheap, dear])
    host.keep_in(inst.state_dir)
    # The default account is over its threshold on a reading a minute old: it refuses.
    host.keep_reading(MINUTE, payload(session=99.0, weekly=6.0))
    personal = claude_account.resolve(inst, PERSONAL)
    key = claude_account.account_key(personal)
    # `personal` has an old reading and a cooling endpoint, so its start rests on an estimate.
    cache = claude_account.file_for(host.cache, personal)
    cache.write_text(
        json.dumps(
            {
                **payload(session=45.0, weekly=6.0),
                "fetched_at": (datetime.now(UTC) - 180 * MINUTE).isoformat(),
                "cooldown_until": (datetime.now(UTC) + 3 * MINUTE).isoformat(),
                "account": key,
            }
        )
    )
    calls_path(inst.state_dir, personal).write_text(
        json.dumps(
            {
                "at": (datetime.now(UTC) - 2 * MINUTE).isoformat(),
                "caller": "guard",
                "outcome": "rate_limited",
                "status": 429,
                "headers": {"retry-after": "0"},
                "account": key,
            }
        )
        + "\n"
    )

    round_of(inst, store)

    kept = json.loads(cache.read_text())
    # The account was on its estimate, and the unit that runs on it is the only one kept.
    assert kept.get("estimate_units") == ["two/1"]
