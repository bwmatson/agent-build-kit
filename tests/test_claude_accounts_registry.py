"""A repo names a Claude account by label and each person supplies the directory; a label with
no directory on this machine is the default account (spec: claude-accounts)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit import claude_account
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import CLAUDE_CODE, ConfigError, load
from agent_build_kit.installation import Installation, load_installation
from tests.account_settings import Configure
from tests.cli.claude_auth_fakes import FakeClaude, in_planning_env, said
from tests.cli.test_doctor import workspace  # noqa: F401 — fixture
from tests.factories import which_all

APP = {"path": ".", "slug": "example/app"}
CHECK = "claude account"

# Each account function, called the way a caller with no account calls it.
FUNCTIONS: dict[str, Callable[..., Any]] = {
    "home": claude_account.home,
    "environment_entry": claude_account.environment_entry,
    "credentials_path": claude_account.credentials_path,
    "state_file": claude_account.state_file,
    "skills_dir": claude_account.skills_dir,
    "account_key": claude_account.account_key,
}


def planning_files(root: Path, *, committed: dict | None = None, local: dict | None = None) -> Path:
    """`abk.yaml` (and `abk.local.yaml` when `local` is given) in `root`; the path of the first."""
    path = root / "abk.yaml"
    path.write_text(yaml.safe_dump(committed or {"repos": {"app": {**APP, "account": "kit"}}}))
    if local is not None:
        (root / "abk.local.yaml").write_text(yaml.safe_dump(local))
    return path


def kit_overlay(config_dir: Path | str | None, **account: Any) -> dict:
    entry = dict(account) if config_dir is None else {"config_dir": str(config_dir), **account}
    return {"runtimes": {CLAUDE_CODE: {"accounts": {"kit": entry}}}}


def installation(root: Path, *, local: dict | None) -> Installation:
    """The installation of a planning repo under `root`, which the worktree root (under `HOME`)
    must not contain."""
    planning = root / "plan"
    planning.mkdir()
    return load_installation(planning_files(planning, local=local))


def test_a_config_dir_in_the_committed_file_fails_naming_the_file_and_the_key(
    tmp_path: Path,
) -> None:
    committed = {
        "repos": {"app": {**APP, "account": "kit"}},
        **kit_overlay(tmp_path / "kit-home"),
    }

    with pytest.raises(ConfigError) as refused:
        load(planning_files(tmp_path, committed=committed))

    assert "abk.yaml" in str(refused.value)
    assert "abk.local.yaml" not in str(refused.value)
    assert "config_dir" in str(refused.value)


def test_a_relative_config_dir_in_the_overlay_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as refused:
        load(planning_files(tmp_path, local=kit_overlay("accounts/kit")))

    assert "abk.local.yaml" in str(refused.value)
    assert "config_dir" in str(refused.value)
    assert "absolute" in str(refused.value)


def test_a_label_with_a_config_dir_resolves_to_that_account(tmp_path: Path) -> None:
    directory = tmp_path / "kit-home"
    overlay = kit_overlay(
        directory, limits={"weekly": {"usage_pause_pct": 40}}, max_units_in_progress=2
    )
    inst = installation(tmp_path, local=overlay)
    assert inst.config.repos["app"].account == "kit"
    loaded = inst.config.runtimes[CLAUDE_CODE].accounts["kit"]
    assert loaded.config_dir == directory
    assert loaded.limits.weekly.usage_pause_pct == 40
    assert loaded.max_units_in_progress == 2

    account = claude_account.resolve(inst, "kit")

    assert account.label == "kit"
    assert account.config_dir == directory
    assert account.limits.weekly.usage_pause_pct == 40
    assert account.max_units_in_progress == 2


def test_a_labelled_account_answers_every_function_from_its_directory(tmp_path: Path) -> None:
    directory = tmp_path / "kit-home"
    account = claude_account.resolve(installation(tmp_path, local=kit_overlay(directory)), "kit")

    assert claude_account.home(account) == directory
    assert claude_account.environment_entry(account) == {claude_account.VARIABLE: str(directory)}
    assert claude_account.credentials_path(account) == directory / ".credentials.json"
    assert claude_account.state_file(account) == directory / ".claude.json"
    assert claude_account.skills_dir(account) == directory / "skills"
    assert claude_account.account_key(account) == str(directory)


@pytest.mark.parametrize("overlay", [None, kit_overlay(None, max_units_in_progress=3)])
def test_a_label_without_a_config_dir_is_the_default_account(
    tmp_path: Path, overlay: dict | None
) -> None:
    inst = installation(tmp_path, local=overlay)

    unresolved = claude_account.resolve(inst, "kit")

    assert unresolved == claude_account.resolve(inst, None)
    assert unresolved.label is None and unresolved.config_dir is None


def test_no_label_is_the_default_account_with_the_runtimes_limits(tmp_path: Path) -> None:
    inst = installation(tmp_path, local=kit_overlay(tmp_path / "kit-home"))

    account = claude_account.resolve(inst, None)

    assert account.label is None
    assert account.limits == inst.config.runtimes[CLAUDE_CODE].limits


@pytest.mark.parametrize("name", FUNCTIONS)
@pytest.mark.parametrize("label", [None, "kit"])
@pytest.mark.parametrize("default_dir", [None, "second"])
def test_with_no_accounts_every_function_returns_what_it_did_before(
    tmp_path: Path, configure: Configure, name: str, label: str | None, default_dir: str | None
) -> None:
    dotenv = {} if default_dir is None else {"CLAUDE_CONFIG_DIR": str(tmp_path / default_dir)}
    configure(dotenv=dotenv)
    inst = installation(tmp_path, local=None)
    function = FUNCTIONS[name]

    account = claude_account.resolve(inst, label)

    assert function(account) == function(claude_account.Account.default())


def accounts_checks(workspace: Path, run: FakeClaude) -> list[Check]:  # noqa: F811 — fixture
    return [
        c for c in run_doctor(workspace / "abk.yaml", run=run, which=which_all) if c.name == CHECK
    ]


def name_the_label(workspace: Path, directory: Path | None) -> None:  # noqa: F811 — fixture
    """`repos.app.account: kit` in the committed file; the overlay defines `kit` when given."""
    path = workspace / "abk.yaml"
    document = yaml.safe_load(path.read_text())
    document["repos"]["app"]["account"] = "kit"
    path.write_text(yaml.safe_dump(document))
    if directory is not None:
        (workspace / "abk.local.yaml").write_text(yaml.safe_dump(kit_overlay(directory)))


def test_doctor_prints_one_note_for_an_unresolved_label(
    workspace: Path,  # noqa: F811 — fixture
    configure: Configure,
) -> None:
    in_planning_env(workspace, configure)
    name_the_label(workspace, None)

    checks = accounts_checks(workspace, FakeClaude())

    (note,) = checks
    assert note.status == "info"
    assert "kit" in said([note]) and "default account" in said([note])


def test_doctor_reports_a_missing_config_dir_with_the_login_command(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
) -> None:
    directory = tmp_path / "never-made"
    in_planning_env(workspace, configure)
    name_the_label(workspace, directory)
    run = FakeClaude()

    checks = accounts_checks(workspace, run)

    assert [c.status for c in checks] == ["FAIL"]
    assert "does not exist" in said(checks)
    assert checks[0].fix == f"{claude_account.VARIABLE}={directory} claude auth login"
    assert [env for _, env in run.asked if env and env.get(claude_account.VARIABLE)] == []


def test_doctor_reports_a_config_dir_not_logged_in_with_the_login_command(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
) -> None:
    directory = tmp_path / "kit-home"
    directory.mkdir()
    in_planning_env(workspace, configure)
    name_the_label(workspace, directory)

    checks = accounts_checks(workspace, FakeClaude(status=1, logged_in=False))

    assert [c.status for c in checks] == ["FAIL"]
    assert "not logged in" in said(checks)
    assert checks[0].fix == f"{claude_account.VARIABLE}={directory} claude auth login"


def test_doctor_says_nothing_of_accounts_for_an_installation_with_none(
    workspace: Path,  # noqa: F811 — fixture
    configure: Configure,
    tmp_path: Path,
) -> None:
    in_planning_env(workspace, configure)
    inst = load_installation(workspace / "abk.yaml")

    assert accounts_checks(workspace, FakeClaude()) == []
    assert claude_account.resolve(inst, None) == claude_account.Account()
