"""An installation that recorded a runtime as unchecked is still warned about with no check,
and `abk init` no longer records that marker, because it no longer asks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import run_doctor
from agent_build_kit.runtimes import policy_check
from tests.cli.policy_step_fakes import Operator, configured, recorded
from tests.cli.test_doctor import Answers, by_name, which_all
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.runtimes.selectable import SelectableRuntime, spelling_report


def test_init_records_no_marker_and_doctor_still_warns_about_one_already_recorded(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # A runtime whose check leaves a class open and which has no fix: init is asked about it.
    runtime = SelectableRuntime("loose", reports=(spelling_report(),))
    planning = configured(tmp_path, app, monkeypatch, runtime)
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "3", otherwise="1"))

    main(init_args(planning, app))

    assert "policy" not in recorded(planning, "loose")

    path = planning / "abk.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["runtimes"]["loose"]["policy"] = "unchecked"
    path.write_text(yaml.safe_dump(raw))

    def never(*args: object, **kwargs: object) -> None:
        pytest.fail("a runtime recorded as unchecked was checked")

    monkeypatch.setattr(policy_check, "check_policy", never)

    checks = by_name(run_doctor(path, run=Answers(), which=which_all))

    assert checks["runtime policy"].status == "warn"
    assert "unchecked" in checks["runtime policy"].detail
