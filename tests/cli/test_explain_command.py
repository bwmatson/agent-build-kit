# ruff: noqa: F811 — the imported fixture is requested by name
"""`abk explain <unit> [--at TIME]` says, from the admission records, why a unit was admitted,
held or paused at a time (spec: capacity-checks, admission leaves a record that explains it)."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    config_fingerprint,
    read_admissions,
)
from tests import fake_clock
from tests.cli.test_admission_asks_own_account import (  # noqa: F401 — fixtures
    PERSONAL,
    Accounts,
    accounts,
    isolated,
    round_of,
    unit,
)
from tests.pipeline.test_admission_record import in_review, installation


def explain(
    inst: Installation, uid: str, capsys: pytest.CaptureFixture[str], *, at: str | None = None
) -> tuple[int, str]:
    capsys.readouterr()
    code = cmd_explain(argparse.Namespace(unit=uid, at=at), inst)
    return code, capsys.readouterr().out


def test_it_says_why_a_unit_was_admitted_with_the_count_the_usage_decision_and_the_tick(
    tmp_path: Path, accounts: Accounts, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store = installation(tmp_path, [unit("busy/1", "app"), unit("one/1", "app")], limit=3)
    in_review(store, "busy/1", 12)
    round_of(inst, store)
    [record] = read_admissions(inst.state_dir / ADMISSIONS_NAME)

    code, out = explain(inst, "one/1", capsys)

    assert code == 0
    assert "admitted" in out
    assert "busy/1" in out
    assert "limit 3" in out
    assert "plenty" in out
    assert record.tick in out
    assert config_fingerprint(inst) in out


def test_it_says_a_unit_was_held_at_a_full_slot_and_names_the_units_counted(
    tmp_path: Path, accounts: Accounts, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store = installation(tmp_path, [unit("busy/1", "app"), unit("next/1", "app")], limit=1)
    in_review(store, "busy/1", 12)
    round_of(inst, store)

    code, out = explain(inst, "next/1", capsys)

    assert code == 0
    assert "held" in out
    assert "busy/1" in out
    assert "limit 1" in out


def test_it_says_a_unit_was_paused_by_its_account_and_why(
    tmp_path: Path, accounts: Accounts, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    accounts.full = {PERSONAL}
    round_of(inst, store)

    code, out = explain(inst, "two/1", capsys)

    assert code == 0
    assert "paused" in out
    assert f"account {PERSONAL}" in out
    assert "weekly usage at 93%" in out
    [refusal] = [
        each for each in read_admissions(inst.state_dir / ADMISSIONS_NAME) if each.kind == "usage"
    ]
    assert f"tick {refusal.tick}" in out
    assert config_fingerprint(inst) in out
    assert "limit 5" in out
    assert "stale configuration" not in out


def test_an_at_that_is_not_an_iso_time_is_refused_with_what_is_expected(
    tmp_path: Path, accounts: Accounts, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store = installation(tmp_path, [unit("one/1", "app")])

    code = cmd_explain(argparse.Namespace(unit="one/1", at="yesterday"), inst)

    assert code == 2
    assert "--at expects an ISO time" in capsys.readouterr().err


def test_at_selects_the_record_in_force_at_that_time(
    tmp_path: Path,
    accounts: Accounts,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clock = fake_clock.install(monkeypatch)
    inst, store = installation(
        tmp_path, [unit("busy/1", "app"), unit("busy/2", "app"), unit("next/1", "app")], limit=1
    )
    in_review(store, "busy/1", 12)
    first = clock.now()
    round_of(inst, store)
    clock.advance(3600)
    in_review(store, "busy/2", 13)
    round_of(inst, store)

    _, then = explain(inst, "next/1", capsys, at=(first + timedelta(minutes=30)).isoformat())
    _, now = explain(inst, "next/1", capsys)

    assert "busy/1" in then
    assert "busy/2" not in then
    assert "busy/2" in now


def test_it_says_plainly_when_no_record_covers_the_time(
    tmp_path: Path,
    accounts: Accounts,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clock = fake_clock.install(monkeypatch)
    inst, store = installation(tmp_path, [unit("one/1", "app")])
    before = clock.now() - timedelta(days=1)
    round_of(inst, store)

    _, early = explain(inst, "one/1", capsys, at=before.isoformat())
    _, unknown = explain(inst, "nothing/1", capsys)

    assert "no record" in early
    assert "no record" in unknown


def test_it_marks_a_decision_made_on_a_configuration_the_files_no_longer_match(
    tmp_path: Path, accounts: Accounts, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app")])
    round_of(inst, store)
    _, current = explain(inst, "one/1", capsys)
    (inst.root / "abk.local.yaml").write_text("project_limits:\n  max_units_in_progress: 2\n")

    _, changed = explain(inst, "one/1", capsys)

    assert "stale configuration" not in current
    assert "stale configuration" in changed
