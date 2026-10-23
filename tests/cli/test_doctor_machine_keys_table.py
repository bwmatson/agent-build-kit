"""`abk doctor`'s `machine keys` check reads the table of machine settings: a warning for each
machine choice, a note for each default, naming the key path and never the value, with the fix
that names `abk config --migrate` (spec: config-migration)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit import machine_settings as table
from agent_build_kit.cli.doctor import MACHINE_KEYS, Check, run_doctor
from agent_build_kit.config import merge_local
from agent_build_kit.machine_settings import MachineSetting
from tests.cli.public_content_repo import planning, said
from tests.cli.test_doctor import Answers
from tests.factories import git, which_all

OVERLAY = "abk.local.yaml"
WARN_FIX = "move it to abk.local.yaml with `abk config --migrate`"
NOTE_FIX = (
    "fine to commit; move it to abk.local.yaml to differ "
    "(`abk config --migrate --include-defaults` moves it)"
)
ACCOUNTS = {"runtimes": {"claude_code": {"accounts": {"kit": {"max_units_in_progress": 2}}}}}

# Each machine choice: the document that holds it and the value that must never appear in what
# doctor says. The key path doctor names is the dictionary key.
MACHINE_CHOICES = {
    "repos.app.account": (
        {"repos": {"app": {"account": "secret-name"}}, **ACCOUNTS},
        "secret-name",
    ),
    "project_limits": ({"project_limits": {"max_concurrent_stacks": 7321}}, "7321"),
    "runtimes.claude_code.accounts": (ACCOUNTS, "max_units_in_progress"),
    "tests.e2e_available": ({"tests": {"e2e_available": {"os": ["linux"]}}}, "linux"),
    "runtimes.acp.command": (
        {"runtimes": {"acp": {"command": ["/opt/secret/agent", "acp"]}}},
        "/opt/secret/agent",
    ),
    "runtimes.claude_code.policy_fix": (
        {"runtimes": {"claude_code": {"policy_fix": ["/opt/secret/fixer"]}}},
        "/opt/secret/fixer",
    ),
    "repos.app.deploy.ssh_key": (
        {"repos": {"app": {"deploy": {"ssh_key": "~/.ssh/secret-key"}}}},
        "secret-key",
    ),
    "planning.worktree_root": ({"planning": {"worktree_root": "~/secret-trees"}}, "secret-trees"),
    "repos.app.path": ({"repos": {"app": {"path": "../secret-app"}}}, "secret-app"),
    "verify.env.TOKEN.file": (
        {"verify": {"env": {"TOKEN": {"from": "env-file", "file": "~/secret.env", "key": "T"}}}},
        "secret.env",
    ),
    "verify.env.TOKEN.value": (
        {"verify": {"env": {"TOKEN": {"from": "literal", "value": "/home/me/secret-v"}}}},
        "secret-v",
    ),
    "verify.env.TOKEN.argv": (
        {"verify": {"env": {"TOKEN": {"from": "command", "argv": ["cat", "~/secret-a"]}}}},
        "secret-a",
    ),
}
DEFAULTS = {
    "runtimes.claude_code.limits": {
        "runtimes": {"claude_code": {"limits": {"session": {"usage_pause_pct": 70}}}}
    },
    "repos.app.tests.e2e_schedule": {"repos": {"app": {"tests": {"e2e_schedule": False}}}},
    "tests.e2e_splits.slow.hold": {
        "tests": {"e2e_splits": {"slow": {"marker": "slow", "hold": True}}}
    },
}
DECLARED = {"tests": {"e2e_dimensions": {"os": {"linux": {"marker": "linux"}}}}}


def repo(
    root: Path, committed: dict[str, Any], *, tracked: bool = True, repository: bool = True
) -> Path:
    """A planning root whose abk.yaml holds `committed` (tracked, untracked, or outside a
    repository); the path of abk.yaml."""
    config = planning(root, ignore=OVERLAY + "\n", tracked=tracked, repository=repository)
    document = merge_local(merge_local(yaml.safe_load(config.read_text()), DECLARED), committed)
    config.write_text(yaml.safe_dump(document, sort_keys=False))
    if repository and tracked:
        git(root, "commit", "-qam", "machine keys")
    return config


def machine_keys(config: Path) -> list[Check]:
    return [
        check
        for check in run_doctor(config, run=Answers(), which=which_all)
        if check.name == MACHINE_KEYS
    ]


def about(checks: list[Check], key: str) -> list[Check]:
    return [check for check in checks if key in check.detail]


@pytest.mark.parametrize("key", MACHINE_CHOICES)
def test_each_machine_choice_warns_naming_the_key_path_and_never_the_value(
    tmp_path: Path, key: str
) -> None:
    document, value = MACHINE_CHOICES[key]
    config = repo(tmp_path / "plan", document)

    found = about(machine_keys(config), key)

    assert [c.status for c in found] == ["warn"], found
    assert found[0].fix == WARN_FIX
    assert value not in said(found[0])


@pytest.mark.parametrize("key", DEFAULTS)
def test_each_default_is_a_note_whose_fix_names_include_defaults(tmp_path: Path, key: str) -> None:
    config = repo(tmp_path / "plan", DEFAULTS[key])

    found = about(machine_keys(config), key)

    assert [c.status for c in found] == ["info"], found
    assert found[0].fix == NOTE_FIX


def test_an_untracked_file_says_nothing(tmp_path: Path) -> None:
    config = repo(tmp_path / "plan", MACHINE_CHOICES["project_limits"][0], tracked=False)

    assert machine_keys(config) == []


def test_a_directory_that_is_not_a_repository_says_nothing(tmp_path: Path) -> None:
    config = repo(tmp_path / "plan", MACHINE_CHOICES["project_limits"][0], repository=False)

    assert machine_keys(config) == []


def test_runtime_models_say_nothing(tmp_path: Path) -> None:
    models = {"runtimes": {"claude_code": {"models": {"implement": "m"}}}}
    config = repo(tmp_path / "plan", {**models, **MACHINE_CHOICES["project_limits"][0]})

    checks = machine_keys(config)

    assert [c.status for c in about(checks, "project_limits")] == ["warn"]
    assert about(checks, "models") == []


def local_document(key: str) -> dict[str, Any]:
    if key in MACHINE_CHOICES:
        return MACHINE_CHOICES[key][0]
    return DEFAULTS[key]


@pytest.mark.parametrize("key", [*MACHINE_CHOICES, *DEFAULTS])
def test_the_same_keys_in_the_local_file_say_nothing(tmp_path: Path, key: str) -> None:
    sentinel = "tests.e2e_available" if key == "project_limits" else "project_limits"
    config = repo(tmp_path / "plan", MACHINE_CHOICES[sentinel][0])
    (tmp_path / "plan" / OVERLAY).write_text(yaml.safe_dump(local_document(key)))

    checks = machine_keys(config)

    assert [c.status for c in about(checks, sentinel)] == ["warn"]
    assert about(checks, key) == []


def test_a_key_in_a_table_entry_added_by_the_test_is_reported_without_doctor_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original: Callable[..., list[MachineSetting]] = table.machine_settings
    added = [
        MachineSetting(path=("runtimes", "claude_code", "models"), reason="r", kind="machine"),
        MachineSetting(path=("repos", "app", "slug"), reason="r", kind="default"),
    ]
    monkeypatch.setattr(table, "machine_settings", lambda *a, **k: [*original(*a, **k), *added])
    committed = {"runtimes": {"claude_code": {"models": {"implement": "m"}}}}
    config = repo(tmp_path / "plan", committed)

    checks = machine_keys(config)

    machine = about(checks, "runtimes.claude_code.models")
    default = about(checks, "repos.app.slug")
    assert [(c.status, c.fix) for c in machine] == [("warn", WARN_FIX)]
    assert [(c.status, c.fix) for c in default] == [("info", NOTE_FIX)]
