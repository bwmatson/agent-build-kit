"""The units store's connection settings, the one URL builder, and `abk db`
(spec: unit-store, "The connection is five settings with one builder" and "A local install can
start a database"). The database is a SQLite file; Docker is a stand-in at the subprocess seam."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from agent_build_kit import redaction
from agent_build_kit.cli.db_cmd import cmd_db_down, cmd_db_up, cmd_db_upgrade
from agent_build_kit.config import StoreConfig
from agent_build_kit.orchestration.sql.url import store_url
from tests.cli.store_installation import loaded, no_store_env  # noqa: F401
from tests.factories import which_all

NO_ARGS = argparse.Namespace()

# The setting, its value in abk.yaml, in abk.local.yaml, in the environment, and what the
# environment's text loads as.
SETTINGS = [
    ("url", "sqlite+aiosqlite:///file.db", "sqlite+aiosqlite:///local.db", "x://env", "x://env"),
    ("host", "file.example", "local.example", "env.example", "env.example"),
    ("port", 5433, 5434, "5435", 5435),
    ("user", "file-user", "local-user", "env-user", "env-user"),
    ("password", "file-secret", "local-secret", "env-secret", "env-secret"),
    ("database", "file-db", "local-db", "env-db", "env-db"),
]


@pytest.mark.parametrize(("name", "tracked", "local", "env", "loads_as"), SETTINGS)
def test_a_store_setting_loads_from_the_file_then_the_local_file_then_the_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_store_env: None,  # noqa: F811
    name: str,
    tracked: Any,
    local: Any,
    env: str,
    loads_as: Any,
) -> None:
    from_file = loaded(tmp_path / "file", {name: tracked}).store
    with_local = loaded(tmp_path / "local", {name: tracked}, {name: local}).store
    monkeypatch.setenv(f"ABK_STORE_{name.upper()}", env)
    with_env = loaded(tmp_path / "env", {name: tracked}, {name: local}).store

    assert getattr(from_file, name) == tracked
    assert getattr(with_local, name) == local
    assert getattr(with_env, name) == loads_as


def test_the_port_defaults_to_5432(tmp_path: Path, no_store_env: None) -> None:  # noqa: F811
    assert loaded(tmp_path).store.port == 5432


@pytest.mark.parametrize("password", ["p@ss", "pa/ss", "pa:ss", "a@b/c:d"])
def test_the_builder_makes_an_asyncpg_url_that_parses_back_to_its_parts(password: str) -> None:
    url = store_url(StoreConfig(host="db.example", user="abk", password=password, database="units"))

    parsed = make_url(url or "")
    assert parsed.drivername == "postgresql+asyncpg"
    assert (parsed.host, parsed.port) == ("db.example", 5432)
    assert (parsed.username, parsed.password, parsed.database) == ("abk", password, "units")


def test_a_url_that_is_set_is_used_as_given_beside_the_parts() -> None:
    given = "sqlite+aiosqlite:///given.db"

    store = StoreConfig(url=given, host="db.example", user="abk", password="x", database="units")

    assert store_url(store) == given


def test_the_password_is_redacted_whether_it_came_as_a_part_or_inside_the_url(
    tmp_path: Path,
    no_store_env: None,  # noqa: F811
) -> None:
    secret = "s3cr/t@pass:word"
    parts = loaded(
        tmp_path / "parts",
        {"host": "db.example", "user": "abk", "password": secret, "database": "units"},
    )
    written = store_url(StoreConfig(host="h", user="u", password=secret, database="units"))
    given = loaded(tmp_path / "given", {"url": written})

    for inst in (parts, given):
        url = store_url(inst.store) or ""
        text = redaction.gather(inst).redact(f"{secret} {url}")
        assert "s3cr" not in text
        assert "t%40pass" not in text


class Docker:
    """`subprocess.run` for the container calls: it records them and answers a container id."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "container-id\n", "")


def test_db_up_starts_a_container_on_a_free_port_and_prints_its_url(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_store_env: None,  # noqa: F811
) -> None:
    docker = Docker()

    code = cmd_db_up(NO_ARGS, loaded(tmp_path), run=docker, which=which_all)

    out = capsys.readouterr().out
    url = make_url(next(word for word in out.split() if "://" in word))
    [started] = [argv for argv in docker.commands if argv[:2] == ["docker", "run"]]
    published = started[started.index("-p") + 1].split(":")[-2]
    assert code == 0
    assert url.drivername == "postgresql+asyncpg"
    assert url.port == int(published)


def test_db_down_stops_the_container(tmp_path: Path, no_store_env: None) -> None:  # noqa: F811
    docker = Docker()

    code = cmd_db_down(NO_ARGS, loaded(tmp_path), run=docker, which=which_all)

    assert code == 0
    assert [argv for argv in docker.commands if argv[:2] == ["docker", "stop"]]


@pytest.mark.parametrize("command", [cmd_db_up, cmd_db_down])
def test_db_up_and_down_refuse_politely_when_docker_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_store_env: None,  # noqa: F811
    command: Any,
) -> None:
    docker = Docker()

    code = command(NO_ARGS, loaded(tmp_path), run=docker, which=lambda name: None)

    seen = capsys.readouterr()
    assert code == 1
    assert docker.commands == []
    assert "docker" in (seen.out + seen.err).lower()


def test_db_upgrade_brings_the_configured_database_to_the_head_revision(
    tmp_path: Path,
    no_store_env: None,  # noqa: F811
) -> None:
    database = tmp_path / "units.db"
    inst = loaded(tmp_path / "plan", {"url": f"sqlite+aiosqlite:///{database}"})

    code = cmd_db_upgrade(NO_ARGS, inst)

    engine = create_engine(f"sqlite:///{database}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert code == 0
    assert {"units", "unit_history"} <= tables
