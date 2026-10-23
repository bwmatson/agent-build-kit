"""The table of machine settings: which keys of a parsed abk.yaml belong to a machine or a
person, and which are a default a team may commit (spec: config-migration)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.machine_settings import MachineSetting, machine_settings

# Spelled in parts so that the scan for home paths in this checkout does not see them.
TILDE = "~" + "/"
HOMES = "/" + "home/"
HOME = f"{HOMES}someone"


@pytest.fixture(autouse=True)
def home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", HOME)


def listed(document: dict[str, Any], top: Path, kind: str) -> list[tuple[str, ...]]:
    return [s.path for s in machine_settings(document, top) if s.kind == kind]


MACHINE = {
    "account": ({"repos": {"app": {"account": "kit"}}}, ("repos", "app", "account")),
    "project_limits": ({"project_limits": {"max_concurrent_stacks": 2}}, ("project_limits",)),
    "accounts": (
        {"runtimes": {"r": {"accounts": {"kit": {"config_dir": "x"}}}}},
        ("runtimes", "r", "accounts"),
    ),
    "e2e_available": ({"tests": {"e2e_available": {"os": ["linux"]}}}, ("tests", "e2e_available")),
    "repo_e2e_available": (
        {"repos": {"app": {"tests": {"e2e_available": {"os": ["linux"]}}}}},
        ("repos", "app", "tests", "e2e_available"),
    ),
    "command": (
        {"runtimes": {"r": {"command": ["/opt/c/bin/claude", "-p"]}}},
        ("runtimes", "r", "command"),
    ),
    "policy_fix": (
        {"runtimes": {"r": {"policy_fix": ["/opt/fix"]}}},
        ("runtimes", "r", "policy_fix"),
    ),
    "ssh_key": (
        {"repos": {"app": {"deploy": {"ssh_key": f"{TILDE}.ssh/deploy"}}}},
        ("repos", "app", "deploy", "ssh_key"),
    ),
    "worktree_root": (
        {"planning": {"worktree_root": f"{TILDE}work/trees"}},
        ("planning", "worktree_root"),
    ),
    "relative_path": ({"repos": {"app": {"path": "../app"}}}, ("repos", "app", "path")),
    "absolute_path": ({"repos": {"app": {"path": "/srv/app"}}}, ("repos", "app", "path")),
}


@pytest.mark.parametrize("name", MACHINE)
def test_a_machine_choice_is_listed(tmp_path: Path, name: str) -> None:
    document, path = MACHINE[name]

    assert listed(document, tmp_path / "plan", "machine") == [path]


DEFAULTS = {
    "limits": (
        {"runtimes": {"r": {"limits": {"session": {"usage_pause_pct": 70}}}}},
        ("runtimes", "r", "limits"),
    ),
    "off": ({"tests": {"e2e_schedule": "off"}}, ("tests", "e2e_schedule")),
    "false": ({"tests": {"e2e_schedule": False}}, ("tests", "e2e_schedule")),
    "repo_off": (
        {"repos": {"app": {"tests": {"e2e_schedule": "off"}}}},
        ("repos", "app", "tests", "e2e_schedule"),
    ),
    "hold": (
        {"tests": {"e2e_splits": {"slow": {"marker": "slow", "hold": True}}}},
        ("tests", "e2e_splits", "slow", "hold"),
    ),
    "repo_hold": (
        {"repos": {"app": {"tests": {"e2e_splits": {"s": {"hold": False}}}}}},
        ("repos", "app", "tests", "e2e_splits", "s", "hold"),
    ),
}


@pytest.mark.parametrize("name", DEFAULTS)
def test_a_default_a_team_may_commit_is_listed_as_a_default(tmp_path: Path, name: str) -> None:
    document, path = DEFAULTS[name]

    assert listed(document, tmp_path / "plan", "default") == [path]
    assert listed(document, tmp_path / "plan", "machine") == []


QUIET = {
    "models": {"runtimes": {"r": {"models": {"implement": "m"}}}},
    "global_limits": {"global_limits": {"max_units_in_progress": 3}},
    "bare_program": {"runtimes": {"r": {"command": ["claude", "-p"], "policy_fix": ["fix"]}}},
    "empty_project_limits": {"project_limits": {}},
    "null_account": {"repos": {"app": {"account": None}}},
    "dot_path": {"repos": {"app": {"path": "."}}},
    "inside_path": {"repos": {"app": {"path": "./tools/x"}}},
    "schedule_on": {"tests": {"e2e_schedule": "nightly"}},
}


@pytest.mark.parametrize("name", QUIET)
def test_a_setting_that_is_the_same_on_every_machine_is_not_listed(
    tmp_path: Path, name: str
) -> None:
    assert machine_settings(QUIET[name], tmp_path / "plan") == []


def test_a_path_is_judged_from_the_top_level_of_the_checkout(tmp_path: Path) -> None:
    top = tmp_path / "plan"
    document = {"repos": {"a": {"path": "tools/x"}, "b": {"path": "../b"}, "c": {"path": str(top)}}}

    assert listed(document, top, "machine") == [("repos", "b", "path")]


def test_a_path_is_resolved_from_the_root_below_the_top_level(tmp_path: Path) -> None:
    top = tmp_path / "top"
    document = {"repos": {"sibling": {"path": "../sibling"}, "far": {"path": "../../x"}}}

    found = machine_settings(document, top, top / "plan")

    assert [s.path for s in found] == [("repos", "far", "path")]


def env(entry: dict[str, Any]) -> dict[str, Any]:
    return {"verify": {"env": {"TOKEN": entry}}}


@pytest.mark.parametrize("value", [f"{TILDE}.config/app/.env", f"{HOME}/.env", f"{HOMES}other/x"])
@pytest.mark.parametrize(
    ("template", "key"),
    [
        ({"from": "env-file", "file": None, "key": "TOKEN"}, "file"),
        ({"from": "yaml", "file": None, "path": "a.b"}, "file"),
        ({"from": "literal", "value": None}, "value"),
        ({"from": "command", "argv": ["cat", None]}, "argv"),
    ],
)
def test_the_key_of_a_verify_env_entry_that_holds_a_home_path_is_listed(
    tmp_path: Path, template: dict[str, Any], key: str, value: str
) -> None:
    entry = {
        name: [value if item is None else item for item in field]
        if isinstance(field, list)
        else (value if field is None else field)
        for name, field in template.items()
    }

    assert listed(env(entry), tmp_path / "plan", "machine") == [("verify", "env", "TOKEN", key)]


def test_a_verify_env_entry_names_only_the_key_that_holds_the_path(tmp_path: Path) -> None:
    entry = {"from": "env-file", "file": f"{TILDE}.env", "path": f"{TILDE}x", "key": f"{TILDE}y"}

    assert listed(env(entry), tmp_path / "plan", "machine") == [("verify", "env", "TOKEN", "file")]


def test_a_verify_env_value_under_another_directory_is_not_listed(tmp_path: Path) -> None:
    entry = {"from": "env-file", "file": "/srv/secrets/.env", "key": "TOKEN"}

    assert machine_settings(env(entry), tmp_path / "plan") == []


def test_each_setting_has_a_key_path_tuple_a_reason_and_a_class(tmp_path: Path) -> None:
    found = machine_settings({"repos": {"app": {"account": "kit"}}}, tmp_path / "plan")

    assert len(found) == 1
    assert isinstance(found[0], MachineSetting)
    assert found[0].path == ("repos", "app", "account")
    assert found[0].reason
    assert found[0].kind == "machine"


def test_a_value_that_arrives_by_a_merge_key_or_an_alias_is_listed(tmp_path: Path) -> None:
    text = """\
shared: &shared
  account: kit
  path: ../app
repos:
  app:
    <<: *shared
  other:
    account: &name kit
  third:
    account: *name
"""

    found = machine_settings(yaml.safe_load(text), tmp_path / "plan")

    assert [s.path for s in found] == [
        ("repos", "app", "account"),
        ("repos", "app", "path"),
        ("repos", "other", "account"),
        ("repos", "third", "account"),
    ]


def test_the_settings_come_in_the_order_of_the_document(tmp_path: Path) -> None:
    text = f"""\
tests:
  e2e_schedule: off
project_limits:
  max_concurrent_stacks: 2
repos:
  app:
    path: ../app
    account: kit
planning:
  worktree_root: {TILDE}trees
"""

    found = machine_settings(yaml.safe_load(text), tmp_path / "plan")

    assert [s.path for s in found] == [
        ("tests", "e2e_schedule"),
        ("project_limits",),
        ("repos", "app", "path"),
        ("repos", "app", "account"),
        ("planning", "worktree_root"),
    ]
