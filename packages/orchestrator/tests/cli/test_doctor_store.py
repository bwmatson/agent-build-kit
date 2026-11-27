"""`abk doctor` checks the units store, and `abk status` shows it without its password
(spec: unit-store, "The schema is migrated, and doctor says where it stands")."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.orchestration import sql as sql_package
from packages.orchestrator.tests.cli.test_doctor import Answers
from tests.cli.public_content_repo import committed_config
from tests.cli.store_installation import no_store_env, unused_port  # noqa: F401
from tests.conftest import make_installation
from tests.factories import which_all

MIGRATIONS = Path(sql_package.__file__).parent / "migrations"
SECRET = "hunter2-hunter2"


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url)
    return config


def store_checks(tmp_path: Path, url: str) -> list[Check]:
    config = committed_config(tmp_path / "plan", {"store": {"url": url}})
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [check for check in checks if check.name == "store"]


def test_an_unreachable_server_fails_the_store_check_without_the_password(
    tmp_path: Path,
    no_store_env: None,  # noqa: F811
) -> None:
    url = f"postgresql+asyncpg://abk:{SECRET}@127.0.0.1:{unused_port()}/units"

    found = store_checks(tmp_path, url)

    assert [check.status for check in found] == ["FAIL"]
    assert SECRET not in f"{found[0].detail} {found[0].fix}"


def test_a_database_behind_the_head_fails_naming_the_head_and_the_upgrade_command(
    tmp_path: Path,
    no_store_env: None,  # noqa: F811
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'units.db'}"
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()

    found = store_checks(tmp_path, url)

    assert [check.status for check in found] == ["FAIL"]
    assert head and head in found[0].detail
    assert "abk db upgrade" in found[0].fix


def test_a_database_at_the_head_passes_the_store_check(
    tmp_path: Path,
    no_store_env: None,  # noqa: F811
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'units.db'}"
    command.upgrade(alembic_config(url), "head")

    assert [check.status for check in store_checks(tmp_path, url)] == ["ok"]


@pytest.mark.parametrize(
    "store",
    [
        {"url": f"postgresql+asyncpg://abk:{SECRET}@db.example:5432/units"},
        {"host": "db.example", "user": "abk", "password": SECRET, "database": "units"},
    ],
)
def test_status_shows_the_server_and_never_the_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_store_env: None,  # noqa: F811
    store: dict[str, str],
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    inst = make_installation(tmp_path, planning=dict(state_dir="."), store=store)

    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    out = capsys.readouterr().out

    assert "db.example" in out
    assert SECRET not in out
