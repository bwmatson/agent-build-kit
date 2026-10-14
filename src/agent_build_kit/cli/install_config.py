"""`abk install-config`: a builder installs a staged file the harness will not let it write.

The command runs as the pipeline, not as the agent, so it makes the one write the harness
refuses, under rules kept in one place: the target is inside the worktree the command runs in,
its file name is allow-listed, and the staged file is a regular file under `.abk/proposed/`.
It never runs the file and never touches git.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import atomic_write_bytes
from agent_build_kit.pipeline.shell import git

STAGING = Path(".abk") / "proposed"
ALWAYS_INSTALLABLE = (".pre-commit-config.yaml",)
YAML_SUFFIXES = (".yaml", ".yml")


class Refused(Exception):
    """The request breaks a rule; the message says which."""


def _worktree() -> Path:
    top = git(Path.cwd(), "rev-parse", "--show-toplevel", check=False)
    if top.returncode or not top.stdout.strip():
        raise Refused("the working directory is not in a git worktree")
    return Path(top.stdout.strip()).resolve()


def _staged(worktree: Path, staged: str) -> Path:
    path = worktree / staged
    # `worktree` is resolved already; resolving the folder too would follow a symlinked
    # `.abk` or `.abk/proposed` out of the worktree and accept what is there.
    folder = worktree / STAGING
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(folder):
        raise Refused(f"{staged} is not a regular file under {STAGING}/ of this worktree")
    return path.resolve()


def _target(worktree: Path, target: str, allowed: list[str]) -> Path:
    path = Path(target)
    resolved = (path if path.is_absolute() else worktree / path).resolve()
    if not resolved.is_relative_to(worktree):
        raise Refused(f"{target} is outside this worktree ({worktree})")
    if resolved.name not in allowed:
        raise Refused(
            f"{target} is not on the allow-list of installable files: {', '.join(allowed)}"
        )
    return resolved


def _install(source: Path, target: Path) -> bytes:
    """Install `source` at `target`, and return what was written."""
    content = source.read_bytes()
    if target.name.endswith(YAML_SUFFIXES):
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as error:
            raise Refused(f"{source.name} does not parse as YAML: {error}") from error
    atomic_write_bytes(target, content)
    return content


def cmd_install_config(args: argparse.Namespace, inst: Installation) -> int:
    allowed = [*ALWAYS_INSTALLABLE, *inst.config.builders.installable_files]
    try:
        worktree = _worktree()
        source = _staged(worktree, args.staged)
        target = _target(worktree, args.target, allowed)
        content = _install(source, target)
    except Refused as error:
        print(f"abk install-config: refused: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"abk install-config: failed: {error}", file=sys.stderr)
        return 1
    print(
        f"installed {target.relative_to(worktree)} "
        f"sha256={hashlib.sha256(content).hexdigest()} size={len(content)}"
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "install-config", help="install a staged, allow-listed config file in this worktree"
    )
    parser.add_argument("staged", help="a file under .abk/proposed/ of this worktree")
    parser.add_argument("target", help="where to install it, in this worktree")
    parser.set_defaults(func=cmd_install_config)
