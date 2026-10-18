"""The gate checks of `abk doctor`: the provider's library, a reading, the budget, a standing hold
and a gate command (spec: split-gate-usage, "The status and the doctor show a split's gate
usage"). The split is named `metered` so that the extra `acp` is never confused with it."""

from __future__ import annotations

import builtins
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.pipeline.e2e_holds import SOURCE_GATE, write_hold
from tests.cli.e2e_hold_fakes import planning
from tests.cli.gate_usage_fakes import (
    Reads,
    command_gate,
    gated_planning,
    month_end,
    provider_gate,
    provider_reads,
)
from tests.cli.test_doctor import Answers
from tests.factories import init_repo, which_all
from tests.gate_hold_support import Probe
from tests.redaction_fakes import SECRET

SPLIT = "metered"


class AuthenticationError(Exception):
    """The class a library's refused login raises."""


class Running(Answers):
    """The doctor's runner, except that a gate command (the probe) really runs."""

    def __call__(self, argv, **kwargs):  # noqa: ANN001, ANN204
        if argv and argv[0] == sys.executable:
            return subprocess.run(argv, **kwargs)
        return super().__call__(argv, **kwargs)


def doctor(config: Path, *, which=which_all) -> list[Check]:  # noqa: ANN001
    init_repo(config.parent)
    checks = run_doctor(config, run=Running(), which=which)
    return [check for check in checks if "gate" in check.name]


def imports_during(monkeypatch: pytest.MonkeyPatch, action: Callable[[], object]) -> set[str]:
    """The names imported while `action` runs, with `acp` out of the module table so that
    importing it again is seen."""
    for name in [name for name in sys.modules if name == "acp" or name.startswith("acp.")]:
        monkeypatch.delitem(sys.modules, name)
    seen: set[str] = set()
    real_import = builtins.__import__

    def record(name: str, *args: Any, **kwargs: Any) -> object:
        seen.add(name)
        return real_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", record)
        action()
    return seen


def provider_planning(tmp_path: Path) -> Path:
    return gated_planning(tmp_path, provider_gate(), split=SPLIT)


def test_a_missing_library_is_a_warning_printing_both_forms_of_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "modal", None)
    (tmp_path / "plain").mkdir()
    (tmp_path / "gated").mkdir()
    baseline = imports_during(monkeypatch, lambda: doctor(planning(tmp_path / "plain")))

    checks: list[Check] = []
    imported = imports_during(
        monkeypatch, lambda: checks.extend(doctor(provider_planning(tmp_path / "gated")))
    )

    assert not {"modal", "acp"} & {name.split(".")[0] for name in imported - baseline}
    (missing,) = [check for check in checks if check.status == "warn"]
    assert SPLIT in missing.detail
    assert "uv sync --extra modal" in missing.fix
    assert "agent-build-kit[modal]" in missing.fix
    assert "acp" not in missing.detail + missing.fix


def test_a_reading_that_can_be_taken_is_ok_and_shows_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("80"))

    checks = doctor(provider_planning(tmp_path))

    assert checks and {check.status for check in checks} <= {"ok", "info"}
    assert any("budget" in check.detail and "200" in check.detail for check in checks)


def test_a_call_that_raises_warns_with_the_class_and_the_redacted_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(
        monkeypatch, Reads(error=AuthenticationError(f"login refused for token {SECRET}"))
    )

    config = gated_planning(
        tmp_path,
        provider_gate(),
        split=SPLIT,
        extra=f"verify:\n  env:\n    API_KEY: {{from: literal, value: {SECRET}}}\n",
    )

    checks = doctor(config)

    (failed,) = [check for check in checks if check.status == "warn"]
    assert SPLIT in failed.detail and "AuthenticationError" in failed.detail
    assert all(SECRET not in check.detail + check.fix for check in checks)


def hold_by_gate(config: Path) -> None:
    write_hold(
        config.parent,
        SPLIT,
        reason="modal usage 134.00 of 200 USD",
        source=SOURCE_GATE,
        by="gate evaluation",
        until=month_end(),
        now=datetime.now(UTC),
    )


def test_a_standing_gate_hold_is_information_and_not_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 67% is under the threshold of 70%, but inside the resume buffer: the hold stands.
    provider_reads(monkeypatch, Reads("134"))
    config = provider_planning(tmp_path)
    hold_by_gate(config)

    checks = doctor(config)

    held = [check for check in checks if check.status == "info" and SPLIT in check.detail]
    assert held and "held" in held[0].detail
    assert not [check for check in checks if check.status in ("warn", "FAIL")]


def test_the_same_reading_without_the_hold_is_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("134"))

    checks = doctor(provider_planning(tmp_path))

    assert [check for check in checks if "usable" in check.detail and check.status == "ok"]
    assert not [check for check in checks if check.status != "ok"]


def test_a_workspace_with_no_gate_has_no_gate_check(tmp_path: Path) -> None:
    init_repo(tmp_path)
    checks = run_doctor(planning(tmp_path), run=Running(), which=which_all)

    assert not [check for check in checks if "gate" in check.name]


def test_the_doctor_reads_afresh_and_does_not_use_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = provider_reads(monkeypatch, Reads("80"))
    config = provider_planning(tmp_path)

    doctor(config)
    doctor(config)

    assert reads.calls == 2


def test_a_command_gate_is_checked_for_being_found_and_for_its_result(tmp_path: Path) -> None:
    probe = Probe(tmp_path / "bin", SPLIT, 3)

    checks = doctor(gated_planning(tmp_path, command_gate(probe), split=SPLIT))

    assert checks and all(check.status != "FAIL" for check in checks)
    assert any("quota spent" in check.detail for check in checks)
    assert probe.runs == 1


def test_a_command_that_is_not_found_is_a_warning_naming_it(tmp_path: Path) -> None:
    config = gated_planning(tmp_path, "command: [no-such-probe, --quota]", split=SPLIT)

    checks = doctor(config, which=lambda name: None if name == "no-such-probe" else which_all(name))

    (missing,) = [check for check in checks if check.status == "warn"]
    assert "no-such-probe" in missing.detail and SPLIT in missing.detail


def test_only_a_split_with_a_gate_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("80"))

    checks = doctor(provider_planning(tmp_path))

    assert checks and all("claude_code" not in check.detail for check in checks)
