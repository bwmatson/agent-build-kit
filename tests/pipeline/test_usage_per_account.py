"""The usage guard reads, caches and judges per account (spec: claude-accounts, usage and slots
are per account).

Two accounts keep their own windows and caches, a start is judged on its own account's limits,
and a refusal names the account that is full. Only the endpoint and the home directory are faked
(`tests/usage_host.py`); the account is the one a unit's repo resolves to.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_build_kit import claude_account
from agent_build_kit import config as config_module
from agent_build_kit.claude_account import Account
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.pipeline.usage_allowances import (
    ALLOWANCES_NAME,
    allowances_path,
    write_allowances,
)
from agent_build_kit.pipeline.usage_calls import calls_path
from agent_build_kit.pipeline.usage_guard import (
    UsageReading,
    current_usage,
    decide_start,
    held_usage,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, append_record
from agent_build_kit.pipeline.wiring import build_usage_gate
from tests.usage_allowance_records import calibrated, spend
from tests.usage_host import Host, pause_at, payload

MINUTE = timedelta(minutes=1)


def accounts(
    host: Host, *, default: dict[str, Any], kit: dict[str, Any]
) -> tuple[Account, Account]:
    """The default account with limits `default` and the `kit` account with `kit`, as a repo's
    label resolves them."""
    directory = host.home / "kit-account"
    directory.mkdir()
    config = WorkspaceConfig.model_validate(
        {
            "runtimes": {
                "claude_code": {
                    "limits": default,
                    "accounts": {"kit": {"config_dir": str(directory), "limits": kit}},
                }
            }
        }
    )
    config_module.activate(config, None)
    return claude_account.resolve_in(config, None), claude_account.resolve_in(config, "kit")


def session(reading: UsageReading | None) -> int | None:
    return None if reading is None else reading.session_pct


def test_two_accounts_keep_separate_windows_and_caches(host: Host) -> None:
    default, kit = accounts(host, default=pause_at(92), kit=pause_at(92))
    host.answers = [payload(session=61.0), payload(session=10.0)]

    first = current_usage(account=default)
    second = current_usage(account=kit)

    assert (session(first), session(second)) == (61, 10)
    assert host.asked == 2
    assert (session(held_usage(account=default)), session(held_usage(account=kit))) == (61, 10)
    # Each is answered again from its own cache: the other account's call is no reason to ask.
    assert session(current_usage(account=default)) == 61
    assert session(current_usage(account=kit)) == 10
    assert host.asked == 2


def test_a_start_is_judged_against_its_own_accounts_limits(host: Host) -> None:
    default, kit = accounts(host, default=pause_at(92), kit=pause_at(50))
    host.answers = [payload(weekly=60.0), payload(weekly=60.0)]

    on_default = decide_start(account=default)
    on_kit = decide_start(account=kit)

    assert on_default.may_start
    assert not on_kit.may_start


def test_the_default_accounts_thresholds_are_the_runtime_limits_and_an_unresolved_label_is_it(
    host: Host,
) -> None:
    default, kit = accounts(host, default=pause_at(40), kit=pause_at(95))
    host.answers = [payload(weekly=60.0), payload(weekly=60.0), payload(weekly=60.0)]
    unresolved = claude_account.resolve_in(
        WorkspaceConfig.model_validate(
            {"runtimes": {"claude_code": {"limits": pause_at(40), "accounts": {"kit": {}}}}}
        ),
        "kit",
    )

    assert not decide_start(account=default).may_start
    assert decide_start(account=kit).may_start
    assert not decide_start(account=unresolved).may_start


def test_a_paused_account_does_not_stop_another_and_the_pause_names_it(host: Host) -> None:
    default, kit = accounts(host, default=pause_at(92), kit=pause_at(70))
    host.answers = [payload(weekly=10.0), payload(weekly=80.0)]
    may_start_default, _ = build_usage_gate(account=default)
    may_start_kit, _ = build_usage_gate(account=kit)

    allowed, said = may_start_default()
    allowed_kit, why = may_start_kit()

    assert allowed
    assert "kit" not in said
    assert not allowed_kit
    assert "kit" in why
    assert "weekly" in why


def test_an_estimate_for_an_account_uses_its_own_allowances_and_its_own_units(
    host: Host,
) -> None:
    default, kit = accounts(host, default=pause_at(80), kit=pause_at(80))
    key = claude_account.account_key(kit)
    state = host.cache.parent
    state.mkdir(parents=True, exist_ok=True)
    # The `kit` reading is stale and the endpoint is cooling, so the start rests on an estimate.
    cache = claude_account.file_for(host.cache, kit)
    cache.write_text(
        json.dumps(
            {
                **payload(session=0.0, weekly=70.0),
                "fetched_at": (datetime.now(UTC) - 89 * MINUTE).isoformat(),
                "cooldown_until": (datetime.now(UTC) + 3 * MINUTE).isoformat(),
                "account": key,
            }
        )
    )
    calls_path(state, kit).write_text(
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
    # Three units of the default account and one of `kit` have spent since the reading.
    for index in range(3):
        append_record(state / LEDGER_NAME, spend(f"app/{index}", datetime.now(UTC) - 10 * MINUTE))
    own = spend("platform/1", datetime.now(UTC) - 10 * MINUTE).model_copy(update={"account": key})
    append_record(state / LEDGER_NAME, own)
    write_allowances(allowances_path(state, kit), {"weekly": calibrated(1)})
    write_allowances(state / ALLOWANCES_NAME, {"weekly": calibrated(5)})

    decision = decide_start(account=kit)

    assert "weekly ~71% estimated (70% read + 1% spent)" in decision.reason
    assert decision.may_start
    assert host.asked == 0
