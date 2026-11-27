"""`abk db`: start and stop a local PostgreSQL container, and migrate the units store."""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
from typing import Any

from alembic import command

from agent_build_kit.config import StoreConfig
from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.sql.migrate import alembic_config
from agent_build_kit.orchestration.sql.url import redacted, store_url
from agent_build_kit.runtimes.base import Run, Which

CONTAINER = "abk-store"
VOLUME = "abk-store-data"
IMAGE = "postgres:17"
# A throwaway server on the loopback interface: the volume keeps the first password, so it is fixed.
LOCAL = StoreConfig(host="127.0.0.1", user="abk", password="abk", database="abk")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _docker(which: Which) -> bool:
    if which("docker") is None:
        print("abk db: Docker is not installed or not on the PATH", file=sys.stderr)
        return False
    return True


def _failed(done: subprocess.CompletedProcess[Any]) -> bool:
    if done.returncode == 0:
        return False
    print(f"abk db: docker failed: {done.stderr}".rstrip(), file=sys.stderr)
    return True


def cmd_db_up(
    args: argparse.Namespace,
    inst: Installation,
    *,
    run: Run = subprocess.run,
    which: Which = shutil.which,
) -> int:
    """Start a PostgreSQL container on a free port and print its URL; 1 when Docker is missing."""
    if not _docker(which):
        return 1
    port = _free_port()
    started = run(
        [
            "docker", "run", "-d", "--rm", "--name", CONTAINER,
            "-p", f"127.0.0.1:{port}:5432",
            "-e", f"POSTGRES_USER={LOCAL.user}",
            "-e", f"POSTGRES_PASSWORD={LOCAL.password}",
            "-e", f"POSTGRES_DB={LOCAL.database}",
            "-v", f"{VOLUME}:/var/lib/postgresql/data",
            IMAGE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    if _failed(started):
        return 1
    print(store_url(LOCAL.model_copy(update={"port": port})))
    return 0


def cmd_db_down(
    args: argparse.Namespace,
    inst: Installation,
    *,
    run: Run = subprocess.run,
    which: Which = shutil.which,
) -> int:
    """Stop the container `abk db up` started; 1 when Docker is missing."""
    if not _docker(which):
        return 1
    stopped = run(["docker", "stop", CONTAINER], capture_output=True, text=True, check=False)
    return 1 if _failed(stopped) else 0


def cmd_db_upgrade(args: argparse.Namespace, inst: Installation) -> int:
    """Bring the configured database to the head revision."""
    url = store_url(inst.store)
    if url is None:
        print("abk db: no store is configured; set store.url or store.host", file=sys.stderr)
        return 1
    command.upgrade(alembic_config(url), "head")
    print(f"upgraded {redacted(url)}")
    return 0


def register(sub: Any) -> None:
    db = sub.add_parser("db", help="start, stop and migrate the units store's database")
    actions = db.add_subparsers(dest="db_command", required=True)
    for name, func, text in (
        ("up", cmd_db_up, "start a PostgreSQL container and print its URL"),
        ("down", cmd_db_down, "stop the container `abk db up` started"),
        ("upgrade", cmd_db_upgrade, "bring the database to the head revision"),
    ):
        actions.add_parser(name, help=text).set_defaults(func=func)
