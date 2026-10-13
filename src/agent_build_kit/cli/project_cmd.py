"""`abk project init`: register a project in a repo's abk.yaml, and on request write the
smallest manifest its profile recognises.

The entry is written through `init.scaffold.add_project`, the comment-keeping splice
`abk init` uses, so every comment, the key order and the quoting stay as they were; a file
whose layout it cannot follow is refused rather than rewritten."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path, PurePosixPath

from agent_build_kit import profiles
from agent_build_kit import settings as settings_module
from agent_build_kit.config import locate
from agent_build_kit.init.scaffold import ScaffoldError, add_project
from agent_build_kit.installation import Installation


class ProjectInitError(Exception):
    pass


def _normal(path: str) -> str:
    """`path` as a repo-relative `/` path without a leading `./` or trailing `/`; `.` is the
    repo root. An absolute path or one with a `..` part is refused: it names no directory of
    the repo."""
    parts = PurePosixPath(path)
    if parts.is_absolute() or ".." in parts.parts:
        raise ProjectInitError(f"{path!r} is not a path inside the repo")
    return parts.as_posix()


def cmd_project_init(args: argparse.Namespace, inst: Installation) -> int:
    repos = inst.config.repos
    try:
        path = _normal(args.path)
        if args.repo not in repos:
            raise ProjectInitError(
                f"no repo {args.repo!r} in abk.yaml (declared: {', '.join(repos)})"
            )
        if args.profile not in profiles.names():
            raise ProjectInitError(
                f"unknown profile {args.profile!r} (registered: {', '.join(profiles.names())})"
            )
        for existing in repos[args.repo].projects:
            if _normal(existing.path) == path:
                raise ProjectInitError(
                    f"{args.repo} already registers {existing.path!r} (profile {existing.profile})"
                )
        add_project(
            locate(args.config or settings_module.settings.config),
            args.repo,
            {"path": path, "profile": args.profile},
        )
    except (ProjectInitError, ScaffoldError) as error:
        print(f"abk: {error}", file=sys.stderr)
        return 1
    print(f"registered {path} ({args.profile}) in {args.repo}")
    if args.scaffold:
        directory = repos[args.repo].path / path
        _scaffold(directory, args.profile, directory.resolve().name)
    return 0


def _scaffold(directory: Path, profile: str, name: str) -> None:
    manifest = profiles.scaffold_manifest(profile, name)
    if manifest is None:
        print(f"the {profile} profile has no scaffold; no manifest written")
        return
    filename, text = manifest
    target = directory / filename
    if target.exists():
        print(f"{target} exists; left alone")
        return
    directory.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    print(f"wrote {target}")


def register(sub: argparse._SubParsersAction) -> None:
    project = sub.add_parser("project", help="work on the projects a repo registers")
    commands = project.add_subparsers(dest="project_command", required=True)
    init = commands.add_parser("init", help="register a project in a repo, before it exists")
    init.add_argument("path", help="the project's directory, relative to the repo root")
    init.add_argument("--profile", required=True, help="the project's toolchain profile")
    init.add_argument("--repo", required=True, help="the repo, as named in abk.yaml")
    init.add_argument(
        "--scaffold", action="store_true", help="write a minimal manifest; never overwrites one"
    )
    init.set_defaults(func=cmd_project_init)
