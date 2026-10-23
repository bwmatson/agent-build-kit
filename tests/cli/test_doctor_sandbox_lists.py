"""`abk doctor` prints each repo's assembled policy lists with the source of each entry, and
nothing of the kind while the sandbox is off (spec: sandbox-profile-paths)."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoSandboxConfig
from tests.doctor_fakes import ok_run, planning_with
from tests.factories import which_all

# The home shorthand, held apart so no line reads as a path under a home directory.
HOME_MARK = "~"


def sandbox_on(planning: Path) -> None:
    path = planning / "abk.yaml"
    document = yaml.safe_load(path.read_text())
    document["sandbox"] = {"enabled": True}
    path.write_text(yaml.safe_dump(document))


def list_checks(planning: Path) -> list[Check]:
    checks = run_doctor(planning / "abk.yaml", run=ok_run, which=which_all)
    return [c for c in checks if c.name.startswith("policy lists")]


def test_each_repo_lists_its_entries_with_their_sources(tmp_path: Path) -> None:
    extra = str(tmp_path / "extra")
    planning = planning_with(tmp_path, sandbox=RepoSandboxConfig(write=[extra]))
    sandbox_on(planning)

    [check] = list_checks(planning)

    assert check.name == "policy lists app"
    lines = check.detail.splitlines()
    assert any(f"{HOME_MARK}/.cache/uv" in line and "python-uv" in line for line in lines)
    assert any("pypi.org" in line and "python-uv" in line for line in lines)
    assert any(extra in line and "abk.yaml" in line for line in lines)


def test_an_entry_from_the_local_file_names_it(tmp_path: Path) -> None:
    planning = planning_with(tmp_path)
    sandbox_on(planning)
    local = tmp_path / "local-extra"
    (planning / "abk.local.yaml").write_text(
        yaml.safe_dump({"repos": {"app": {"sandbox": {"read": [str(local)]}}}})
    )

    [check] = list_checks(planning)

    assert any(
        str(local) in line and "abk.local.yaml" in line for line in check.detail.splitlines()
    )


def test_only_one_line_is_printed_while_the_sandbox_is_off(tmp_path: Path) -> None:
    planning = planning_with(tmp_path, sandbox=RepoSandboxConfig(write=[str(tmp_path / "x")]))

    checks = run_doctor(planning / "abk.yaml", run=ok_run, which=which_all)

    [line] = [c for c in checks if c.name == "sandbox"]
    assert line.status == "info"
    assert "sandbox.enabled" in line.detail
    assert list_checks(planning) == []
