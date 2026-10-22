"""A rate-limit pause belongs to the account that was refused (spec: capacity-checks, one pause per
account).

`app` runs on the default account and `platform` on `personal`. A pause is a marker in the state
directory: `paused.json` for the default account and `paused.personal.json` for the named one, as
the usage cache is kept per account. A network pause is about the machine and stays one marker.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import network_probe
from agent_build_kit.pipeline.pause import is_paused, pause_until
from agent_build_kit.pipeline.usage_guard import RateLimited
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.cli.test_admission_asks_own_account import (  # noqa: F401 — fixtures
    PERSONAL,
    Accounts,
    accounts,
    isolated,
    round_of,
    unit,
    waits,
    workspace,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")

DEFAULT_MARKER = "paused.json"
PERSONAL_MARKER = f"paused.{PERSONAL}.json"


def write_marker(
    path: Path,
    *,
    reason: str,
    kind: str = "rate_limit",
    account: str | None = None,
    hours: int = 2,
) -> datetime:
    """A pause as a build records it. The account is left out when None, as an older version
    wrote it."""
    until = datetime.now(UTC) + timedelta(hours=hours)
    record = {"until": until.isoformat(), "reason": reason, "kind": kind}
    if account is not None:
        record["account"] = account
    path.write_text(json.dumps(record))
    return until


def refuse_next_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever unit is built next is refused by the model, with a reset in two hours."""
    when = datetime.now(UTC) + timedelta(hours=2)

    class Refusing:
        def run(self, unit, *, base, graph):
            raise RateLimited("usage limit reached", resets_at=when)

    monkeypatch.setattr(cli, "build_runner", lambda unit, **kw: Refusing())


def test_a_refusal_during_a_units_build_pauses_the_account_of_that_unit_and_no_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = workspace(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    refuse_next_build(monkeypatch)

    assert cli.build_unit(inst, store.get("two/1"), store=store) is False

    held = is_paused(inst.state_dir / PERSONAL_MARKER)
    assert held is not None and held.kind == "rate_limit"
    assert json.loads((inst.state_dir / PERSONAL_MARKER).read_text())["account"] == PERSONAL
    assert is_paused(inst.state_dir / DEFAULT_MARKER) is None

    assert cli.build_unit(inst, store.get("one/1"), store=store) is False

    assert is_paused(inst.state_dir / DEFAULT_MARKER) is not None
    assert json.loads((inst.state_dir / PERSONAL_MARKER).read_text())["account"] == PERSONAL


def test_the_other_accounts_units_are_admitted_while_one_account_is_paused_and_its_own_wait(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
) -> None:
    inst, store = workspace(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform"), unit("three/1", "platform")]
    )
    until = write_marker(
        inst.state_dir / PERSONAL_MARKER, reason="rate limited during two/1", account=PERSONAL
    )

    assert round_of(inst, store) == ["one/1"]

    found = waits(inst)
    assert set(found) == {"two/1", "three/1"}
    for wait in found.values():
        assert wait.reason is WaitReason.USAGE_PAUSE
        assert PERSONAL in wait.detail
        assert f"{until.astimezone():%H:%M}" in wait.detail
    assert accounts.asked.get(None) == 1, "the unpaused account's usage is still read"
    assert is_paused(inst.state_dir / DEFAULT_MARKER) is None


def test_a_round_whose_only_ready_units_belong_to_the_paused_account_starts_nothing(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
) -> None:
    inst, store = workspace(tmp_path, [unit("two/1", "platform"), unit("three/1", "platform")])
    write_marker(inst.state_dir / PERSONAL_MARKER, reason="rate limited", account=PERSONAL)

    assert round_of(inst, store) == []

    assert set(waits(inst)) == {"two/1", "three/1"}


def test_a_round_exits_early_only_when_every_account_with_a_startable_unit_is_paused(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
) -> None:
    inst, store = workspace(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    write_marker(inst.state_dir / DEFAULT_MARKER, reason="rate limited during one/1", account=None)
    write_marker(inst.state_dir / PERSONAL_MARKER, reason="rate limited", account=PERSONAL)

    assert round_of(inst, store) == []
    assert accounts.asked == {}, "no reading is taken for a round that cannot start anything"

    (inst.state_dir / DEFAULT_MARKER).unlink()

    assert round_of(inst, store) == ["one/1"]


def test_a_pause_left_by_an_older_version_without_an_account_is_the_default_accounts(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
) -> None:
    inst, store = workspace(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    write_marker(inst.state_dir / DEFAULT_MARKER, reason="rate limited during one/1")

    assert round_of(inst, store) == ["two/1"]

    assert set(waits(inst)) == {"one/1"}
    assert accounts.asked.get(PERSONAL) == 1, "the unpaused account's usage is still read"


def test_a_network_pause_holds_every_account_and_ends_for_all_while_one_account_stays_paused(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inst, store = workspace(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    reachable = False
    monkeypatch.setattr(network_probe, "control_reachable", lambda *a, **k: reachable)
    pause_until(
        datetime.now(UTC) + timedelta(minutes=5),
        reason="network unreachable during one/1",
        marker=inst.state_dir / DEFAULT_MARKER,
        kind="network",
    )
    write_marker(inst.state_dir / PERSONAL_MARKER, reason="rate limited", account=PERSONAL)

    assert round_of(inst, store) == []
    assert not (inst.state_dir / "paused.platform.json").exists()

    reachable = True

    assert round_of(inst, store) == ["one/1"]
    assert is_paused(inst.state_dir / PERSONAL_MARKER) is not None


def test_each_accounts_usage_pause_is_cleared_and_logged_once_when_its_reading_clears(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, store = workspace(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    write_marker(inst.state_dir / DEFAULT_MARKER, reason="weekly usage at 93%", kind="usage")
    write_marker(
        inst.state_dir / PERSONAL_MARKER,
        reason=f"account {PERSONAL}: weekly usage at 93%",
        kind="usage",
        account=PERSONAL,
    )

    assert round_of(inst, store) == ["one/1", "two/1"]

    resumed = [line for line in capsys.readouterr().out.splitlines() if "resuming a pause" in line]
    assert len(resumed) == 2
    assert sum(PERSONAL in line for line in resumed) == 1
    assert is_paused(inst.state_dir / DEFAULT_MARKER) is None
    assert is_paused(inst.state_dir / PERSONAL_MARKER) is None


def test_a_round_does_not_plan_while_the_default_account_is_refused_by_the_model(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planning runs on the default account, so the model's refusal of it holds planning though
    another account's unit starts."""
    inst, store = workspace(tmp_path, [unit("two/1", "platform")])
    planned: list[int] = []
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: planned.append(1))
    write_marker(inst.state_dir / DEFAULT_MARKER, reason="rate limited during one/1")

    assert round_of(inst, store) == ["two/1"]
    assert planned == []

    (inst.state_dir / DEFAULT_MARKER).unlink()

    assert round_of(inst, store) == ["two/1"]
    assert planned == [1]


def test_an_accounts_usage_pause_stays_until_its_own_reading_clears(
    tmp_path: Path,
    accounts: Accounts,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, store = workspace(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    accounts.full = {PERSONAL}
    write_marker(
        inst.state_dir / PERSONAL_MARKER,
        reason=f"account {PERSONAL}: weekly usage at 93%",
        kind="usage",
        account=PERSONAL,
    )

    assert round_of(inst, store) == ["one/1"]

    assert is_paused(inst.state_dir / PERSONAL_MARKER) is not None
    assert not [line for line in capsys.readouterr().out.splitlines() if "resuming" in line]

    accounts.full = set()

    assert round_of(inst, store) == ["one/1", "two/1"]

    resumed = [line for line in capsys.readouterr().out.splitlines() if "resuming a pause" in line]
    assert len(resumed) == 1 and PERSONAL in resumed[0]
    assert is_paused(inst.state_dir / PERSONAL_MARKER) is None


def test_a_marker_belongs_to_the_account_its_file_name_says(tmp_path: Path) -> None:
    write_marker(tmp_path / PERSONAL_MARKER, reason="rate limited")

    held = is_paused(tmp_path / PERSONAL_MARKER)

    assert held is not None and held.account == PERSONAL
    write_marker(tmp_path / DEFAULT_MARKER, reason="rate limited", account=PERSONAL)
    default = is_paused(tmp_path / DEFAULT_MARKER)
    assert default is not None and default.account is None
