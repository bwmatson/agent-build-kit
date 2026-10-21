"""`abk doctor` on machine and person settings in the committed abk.yaml: a warning for a
machine choice, a note for a default a team may commit, nothing for the rest or for the
same keys in abk.local.yaml (spec: config-files-guidance)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.public_content_repo import planning, said
from tests.cli.test_doctor import Answers
from tests.factories import git, which_all

OVERLAY = "abk.local.yaml"
ACCOUNTS = {"runtimes": {"claude_code": {"accounts": {"kit": {"max_units_in_progress": 2}}}}}

# Each machine choice with the document that holds it and the key doctor names.
MACHINE_CHOICES = {
    "repos.app.account": {"repos": {"app": {"account": "kit"}}, **ACCOUNTS},
    "project_limits": {"project_limits": {"max_concurrent_stacks": 2}},
    "runtimes.claude_code.accounts": ACCOUNTS,
    "tests.e2e_available": {"tests": {"e2e_available": {"os": ["linux"]}}},
    "runtimes.acp.command": {"runtimes": {"acp": {"command": ["/opt/tools/some-agent", "acp"]}}},
}
# A default a team may commit: a note, not a warning.
DEFAULTS = {
    "runtimes.claude_code.limits": {
        "runtimes": {"claude_code": {"limits": {"session": {"usage_pause_pct": 70}}}}
    },
    "tests.e2e_splits": {"tests": {"e2e_splits": {"slow": {"marker": "slow", "hold": True}}}},
    "tests.e2e_schedule": {"repos": {"app": {"tests": {"e2e_schedule": "off"}}}},
}
# What describes the workspace, or a program found on the PATH: nothing to say.
QUIET = {
    "runtimes.acp.command": {"runtimes": {"acp": {"command": ["some-agent", "acp"]}}},
    "runtimes.claude_code.models": {"runtimes": {"claude_code": {"models": {"implement": "m"}}}},
}


def merged(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged(base[key], value)
        else:
            base[key] = value
    return base


def installation(root: Path, *, committed: dict[str, Any], overlay: dict[str, Any]) -> Path:
    """A committed planning repo holding `committed` in abk.yaml and `overlay` in the
    ignored abk.local.yaml; the path of abk.yaml."""
    config = planning(root, ignore=OVERLAY + "\n")
    document = yaml.safe_load(config.read_text())
    declared = {"tests": {"e2e_dimensions": {"os": {"linux": {"marker": "linux"}}}}}
    config.write_text(
        yaml.safe_dump(merged(merged(document, declared), committed), sort_keys=False)
    )
    git(root, "commit", "-qam", "machine keys", "--allow-empty")
    (root / OVERLAY).write_text(yaml.safe_dump(overlay))
    return config


# Present in every negative case, so that doctor is shown to look at the file at all.
SENTINEL = "project_limits"


def about(config: Path, key: str) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [check for check in checks if key in said(check) and "abk.yaml" in said(check)]


@pytest.mark.parametrize("key", MACHINE_CHOICES)
def test_a_machine_choice_in_the_committed_file_warns_naming_the_key_and_the_overlay(
    tmp_path: Path, key: str
) -> None:
    config = installation(tmp_path / "plan", committed=MACHINE_CHOICES[key], overlay={})

    found = about(config, key)

    assert [c.status for c in found] == ["warn"], found
    assert "abk.yaml" in said(found[0])
    assert OVERLAY in said(found[0])


@pytest.mark.parametrize("key", DEFAULTS)
def test_a_default_a_team_may_commit_is_a_note_not_a_warning(tmp_path: Path, key: str) -> None:
    config = installation(tmp_path / "plan", committed=DEFAULTS[key], overlay={})

    found = about(config, key)

    assert [c.status for c in found] == ["info"], found
    assert "abk.yaml" in said(found[0])


@pytest.mark.parametrize("key", QUIET)
def test_a_workspace_setting_or_a_bare_program_name_prints_nothing(
    tmp_path: Path, key: str
) -> None:
    config = installation(
        tmp_path / "plan", committed={**MACHINE_CHOICES[SENTINEL], **QUIET[key]}, overlay={}
    )

    assert [c.status for c in about(config, SENTINEL)] == ["warn"]
    assert about(config, key) == []


@pytest.mark.parametrize("key", [*MACHINE_CHOICES, *DEFAULTS])
def test_the_same_keys_only_in_the_overlay_print_nothing(tmp_path: Path, key: str) -> None:
    both = {**MACHINE_CHOICES, **DEFAULTS}
    sentinel = "tests.e2e_available" if key == SENTINEL else SENTINEL
    config = installation(tmp_path / "plan", committed=MACHINE_CHOICES[sentinel], overlay=both[key])

    assert [c.status for c in about(config, sentinel)] == ["warn"]
    assert about(config, key) == []


def test_only_the_keys_present_are_named(tmp_path: Path) -> None:
    config = installation(tmp_path / "plan", committed=MACHINE_CHOICES[SENTINEL], overlay={})

    checks = run_doctor(config, run=Answers(), which=which_all)

    named = [c for c in checks if OVERLAY in said(c) and c.status != "ok"]
    assert [SENTINEL in said(c) for c in named] == [True]
