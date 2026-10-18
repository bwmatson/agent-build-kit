"""`global_limits.e2e_base_runs` allows the one run of the untouched failed tests on the base
(spec: e2e-failures); at 0 the unit fails as it does without it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import LimitsConfig
from tests.conftest import make_installation
from tests.e2e_base_fakes import Runs, branch, pytest_output, session

FAILED = "tests/far/test_one.py::test_one"


def limits(value: int | None = None) -> Any:
    """The limits as the configuration file gives them, read through the schema."""
    return LimitsConfig.model_validate({} if value is None else {"e2e_base_runs": value})


def test_one_base_run_is_allowed_by_default() -> None:
    assert limits().e2e_base_runs == 1


def test_the_base_run_can_be_turned_off() -> None:
    assert limits(0).e2e_base_runs == 0


@pytest.mark.parametrize("value", [2, 3, -1])
def test_a_value_other_than_zero_or_one_is_refused(value: int) -> None:
    with pytest.raises(ValidationError, match="e2e_base_runs") as refused:
        limits(value)

    assert "Extra inputs" not in str(refused.value)


def test_with_the_setting_at_zero_no_base_run_is_made_and_the_unit_fails(
    tmp_path: Path,
) -> None:
    make_installation(tmp_path / "planning", limits={"e2e_base_runs": 0})
    repo, base = branch(tmp_path, {})
    output = pytest_output(failed={FAILED: "assert 1 == 2"})
    runs = Runs(repo, output, output)
    gate = session(tmp_path, runs)

    ok, _ = gate.run(cwd=repo, base=base)

    assert not ok
    assert runs.on_base == []
    assert gate.verdict is None
