"""The machine files are listed once, and the doctor and the migration read that list."""

from __future__ import annotations

import subprocess
from pathlib import Path

import agent_build_kit
from agent_build_kit import config_migrate_write
from agent_build_kit.machine_files import MACHINE_FILES
from tests.cli.in_repo_doctor import checks_of, in_repo, named
from tests.factories import git

SOURCE = Path(agent_build_kit.__file__).parent
MAY_NAME_THE_SCRUB_LIST = {"machine_files.py", "config.py", "scrub_terms.py"}
CONFIG_LOCAL = [name for name in MACHINE_FILES if name != ".env"]


def test_the_list_holds_the_three_files_in_order() -> None:
    assert MACHINE_FILES == (".env", "abk.local.yaml", "scrub.local")


def test_the_doctor_flags_a_tracked_file_of_each_config_local_name(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="branch")
    assert CONFIG_LOCAL == ["abk.local.yaml", "scrub.local"]
    for name in CONFIG_LOCAL:
        (config.parent / name).write_text("x\n")
        git(config.parent, "add", "-f", name)
    git(config.parent, "commit", "-qm", "track the local files")

    details = [check.detail for check in named(checks_of(config), "public content")]

    for name in CONFIG_LOCAL:
        assert f"{name} is tracked" in details


def test_the_migration_ignores_the_list_without_the_env_file() -> None:
    assert config_migrate_write.IGNORED_LOCAL_FILES == tuple(CONFIG_LOCAL)
    assert ".env" in MACHINE_FILES


def test_no_other_module_holds_the_scrub_list_literal() -> None:
    found = subprocess.run(
        ["grep", "-rl", "--include=*.py", '"scrub.local"', str(SOURCE)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()

    assert {Path(path).name for path in found} - MAY_NAME_THE_SCRUB_LIST == set()
