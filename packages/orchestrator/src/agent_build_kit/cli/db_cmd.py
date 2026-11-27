"""`abk db`: start and stop a local PostgreSQL container, and migrate the units store."""

from __future__ import annotations

import argparse
import shutil
import subprocess

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.base import Run, Which


def cmd_db_up(
    args: argparse.Namespace,
    inst: Installation,
    *,
    run: Run = subprocess.run,
    which: Which = shutil.which,
) -> int:
    """Start a PostgreSQL container on a free port and print its URL; 1 when Docker is missing."""
    raise NotImplementedError


def cmd_db_down(
    args: argparse.Namespace,
    inst: Installation,
    *,
    run: Run = subprocess.run,
    which: Which = shutil.which,
) -> int:
    """Stop the container `abk db up` started; 1 when Docker is missing."""
    raise NotImplementedError


def cmd_db_upgrade(args: argparse.Namespace, inst: Installation) -> int:
    """Bring the configured database to the head revision."""
    raise NotImplementedError
