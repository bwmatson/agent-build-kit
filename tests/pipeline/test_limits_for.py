"""`limits_for` resolves the limits that apply to a repo's units: the project block, and for the
repo's account only the fields the account set (spec: account-project-limits)."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit import claude_account, config
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.slots import limits_for, slot_limit, slot_of
from tests.factories import new_unit


def installation(
    root: Path, *, project: dict | None = None, accounts: dict | None = None, labels: dict
) -> Installation:
    """An installation with repos `app` and `platform`, those in `labels` on an account, and the
    accounts (each with a directory) as the machine's overlay gives them."""
    committed: dict = {
        "repos": {
            name: {
                "path": str(root / name),
                "slug": f"example/{name}",
                **({"account": labels[name]} if name in labels else {}),
            }
            for name in ("app", "platform")
        }
    }
    if project is not None:
        committed["project_limits"] = project
    (root / "abk.yaml").write_text(yaml.safe_dump(committed))
    named = {
        label: {"config_dir": str(root / f"{label}-home"), **fields}
        for label, fields in (accounts or {}).items()
    }
    overlay = {"runtimes": {"claude_code": {"accounts": named}}}
    (root / "abk.local.yaml").write_text(yaml.safe_dump(overlay))
    return Installation(config.load(root / "abk.yaml"), root)


def test_a_repo_with_no_account_resolves_to_the_project_block(tmp_path: Path) -> None:
    inst = installation(tmp_path, project={"max_concurrent_stacks": 3}, labels={})

    limits = limits_for(inst, "app")

    assert limits.project == inst.config.project_limits
    assert limits.project.max_concurrent_stacks == 3
    assert limits.account == {}


def test_a_repo_on_the_default_account_has_no_account_limit(tmp_path: Path) -> None:
    accounts = {"kit": {"project_limits": {"max_concurrent_stacks": 1}}}
    inst = installation(tmp_path, accounts=accounts, labels={"platform": "kit"})

    assert limits_for(inst, "app").account == {}


def test_an_account_adds_only_the_fields_it_set(tmp_path: Path) -> None:
    accounts = {"kit": {"project_limits": {"max_concurrent_stacks": 2, "emergency_extra": 0}}}
    inst = installation(tmp_path, accounts=accounts, labels={"app": "kit"})

    limits = limits_for(inst, "app")

    assert limits.account == {"max_concurrent_stacks": 2, "emergency_extra": 0}
    assert limits.project == inst.config.project_limits


def test_an_account_that_sets_nothing_adds_no_limit(tmp_path: Path) -> None:
    inst = installation(tmp_path, accounts={"kit": {}}, labels={"app": "kit"})

    assert limits_for(inst, "app").account == {}


def test_a_label_without_a_directory_adds_no_limit(tmp_path: Path) -> None:
    inst = installation(tmp_path, accounts={}, labels={"app": "kit"})

    assert limits_for(inst, "app").account == {}


def test_the_accounts_units_in_progress_replace_the_projects_for_its_slot(tmp_path: Path) -> None:
    accounts = {"kit": {"project_limits": {"max_units_in_progress": 2}}}
    inst = installation(
        tmp_path,
        project={"max_units_in_progress": 7},
        accounts=accounts,
        labels={"app": "kit"},
    )

    assert slot_limit(inst)("kit") == 2
    assert slot_limit(inst)(None) == 7
    assert slot_of(inst)(new_unit("app-a/1", repo="app")) == "kit"


def test_an_account_that_does_not_set_the_units_in_progress_uses_the_projects(
    tmp_path: Path,
) -> None:
    accounts = {"kit": {"project_limits": {"max_concurrent_stacks": 1}}}
    inst = installation(
        tmp_path,
        project={"max_units_in_progress": 7},
        accounts=accounts,
        labels={"app": "kit"},
    )

    assert slot_limit(inst)("kit") == 7


def test_slots_per_account_is_unchanged_by_a_block(tmp_path: Path) -> None:
    plain = installation(tmp_path, labels={})
    assert not claude_account.slots_per_account(plain.config)

    accounts = {"kit": {"project_limits": {"max_concurrent_stacks": 1}}}
    named = installation(tmp_path, accounts=accounts, labels={})
    assert claude_account.slots_per_account(named.config)
