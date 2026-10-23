"""`abk doctor` on machine and person settings in the committed abk.yaml: a warning for a
machine choice, a note for a default a team may commit, nothing for the rest or for the
same keys in abk.local.yaml (spec: config-files-guidance)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.public_content_repo import (
    ACCOUNTS,
    NOTE_FIX,
    OVERLAY,
    WARN_FIX,
    committed_config,
    said,
)
from tests.cli.test_doctor import Answers
from tests.factories import which_all

# Each machine choice with the document that holds it and the key doctor names.
MACHINE_CHOICES = {
    "repos.app.account": {"repos": {"app": {"account": "kit"}}, **ACCOUNTS},
    "project_limits": {"project_limits": {"max_concurrent_stacks": 2}},
    "runtimes.claude_code.accounts": ACCOUNTS,
    "tests.e2e_available": {"tests": {"e2e_available": {"os": ["linux"]}}},
    "runtimes.acp.command": {"runtimes": {"acp": {"command": ["/opt/tools/some-agent", "acp"]}}},
    "runtimes.claude_code.policy_fix": {
        "runtimes": {"claude_code": {"policy_fix": ["/opt/tools/fixer"]}}
    },
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


# Present in every negative case, so that doctor is shown to look at the file at all.
SENTINEL = "project_limits"


def about(config: Path, key: str) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [check for check in checks if key in said(check) and "abk.yaml" in said(check)]


@pytest.mark.parametrize("key", MACHINE_CHOICES)
def test_a_machine_choice_in_the_committed_file_warns_naming_the_key_and_the_overlay(
    tmp_path: Path, key: str
) -> None:
    config = committed_config(tmp_path / "plan", committed=MACHINE_CHOICES[key], overlay={})

    found = about(config, key)

    assert [c.status for c in found] == ["warn"], found
    assert "abk.yaml" in said(found[0])
    assert found[0].fix == WARN_FIX


@pytest.mark.parametrize("key", DEFAULTS)
def test_a_default_a_team_may_commit_is_a_note_not_a_warning(tmp_path: Path, key: str) -> None:
    config = committed_config(tmp_path / "plan", committed=DEFAULTS[key], overlay={})

    found = about(config, key)

    assert [c.status for c in found] == ["info"], found
    assert "abk.yaml" in said(found[0])
    assert found[0].fix == NOTE_FIX


@pytest.mark.parametrize("key", QUIET)
def test_a_workspace_setting_or_a_bare_program_name_prints_nothing(
    tmp_path: Path, key: str
) -> None:
    config = committed_config(
        tmp_path / "plan", committed={**MACHINE_CHOICES[SENTINEL], **QUIET[key]}, overlay={}
    )

    assert [c.status for c in about(config, SENTINEL)] == ["warn"]
    assert about(config, key) == []


@pytest.mark.parametrize("key", [*MACHINE_CHOICES, *DEFAULTS])
def test_the_same_keys_only_in_the_overlay_print_nothing(tmp_path: Path, key: str) -> None:
    both = {**MACHINE_CHOICES, **DEFAULTS}
    sentinel = "tests.e2e_available" if key == SENTINEL else SENTINEL
    config = committed_config(
        tmp_path / "plan", committed=MACHINE_CHOICES[sentinel], overlay=both[key]
    )

    assert [c.status for c in about(config, sentinel)] == ["warn"]
    assert about(config, key) == []


def test_only_the_keys_present_are_named(tmp_path: Path) -> None:
    config = committed_config(tmp_path / "plan", committed=MACHINE_CHOICES[SENTINEL], overlay={})

    checks = run_doctor(config, run=Answers(), which=which_all)

    named = [c for c in checks if OVERLAY in said(c) and c.status != "ok"]
    assert [SENTINEL in said(c) for c in named] == [True]
