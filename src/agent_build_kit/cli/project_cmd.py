"""`abk project init`: register a project in a repo's abk.yaml, and on request write the
smallest manifest its profile recognises.

The entry is spliced into the file's own lines, so every comment, the key order and the
quoting stay as they were; a file whose layout the splice cannot follow is refused rather
than rewritten."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

from agent_build_kit import profiles
from agent_build_kit.installation import Installation


class ProjectInitError(Exception):
    pass


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_content(line: str) -> bool:
    return bool(line.strip()) and not line.lstrip().startswith("#")


def _block_end(lines: list[str], start: int, inside: Callable[[str], bool]) -> int:
    """The index after the block opened at `lines[start]`, not counting the blank and
    comment lines that trail it (they belong to what follows)."""
    end = start + 1
    for index in range(start + 1, len(lines)):
        if _is_content(lines[index]):
            if not inside(lines[index]):
                break
            end = index + 1
    return end


def _key_line(lines: list[str], key: str, start: int, stop: int, indent: int) -> int | None:
    for index in range(start, stop):
        line = lines[index]
        if (
            _is_content(line)
            and _indent(line) == indent
            and re.match(rf"\s*{re.escape(key)}:", line)
        ):
            return index
    return None


def _first_content(lines: list[str], start: int, stop: int) -> int | None:
    return next((i for i in range(start, stop) if _is_content(lines[i])), None)


def add_entry(text: str, repo: str, entry: dict[str, str]) -> str:
    """`text` with `entry` appended to `repo`'s `projects:` list, created when absent."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    repos = _key_line(lines, "repos", 0, len(lines), 0)
    if repos is None:
        raise ProjectInitError("cannot find the top-level `repos:` in abk.yaml")
    repos_end = _block_end(lines, repos, lambda line: _indent(line) > 0)
    first = _first_content(lines, repos + 1, repos_end)
    if first is None:
        raise ProjectInitError("cannot find a repo entry under `repos:`")
    repo_indent = _indent(lines[first])
    at = _key_line(lines, repo, repos + 1, repos_end, repo_indent)
    if at is None:
        raise ProjectInitError(f"cannot find the `{repo}:` entry in abk.yaml")
    repo_end = _block_end(lines, at, lambda line: _indent(line) > repo_indent)
    child = _first_content(lines, at + 1, repo_end)
    if child is None:
        raise ProjectInitError(f"cannot read the `{repo}:` entry in abk.yaml")
    child_indent = _indent(lines[child])

    def item(indent: int) -> list[str]:
        dumped = yaml.safe_dump([entry], sort_keys=False, default_flow_style=False)
        return [" " * indent + line + "\n" for line in dumped.splitlines()]

    projects = _key_line(lines, "projects", at + 1, repo_end, child_indent)
    if projects is None:
        lines[repo_end:repo_end] = [" " * child_indent + "projects:\n", *item(child_indent + 2)]
        return "".join(lines)
    if lines[projects].split(":", 1)[1].split("#")[0].strip():
        raise ProjectInitError(f"`projects:` of `{repo}` is written inline; edit it by hand")
    listed = _block_end(
        lines,
        projects,
        lambda line: (
            _indent(line) > child_indent
            or (_indent(line) == child_indent and line.lstrip().startswith("-"))
        ),
    )
    first_item = _first_content(lines, projects + 1, listed)
    lines[listed:listed] = item(
        _indent(lines[first_item]) if first_item is not None else child_indent + 2
    )
    return "".join(lines)


def cmd_project_init(args: argparse.Namespace, inst: Installation) -> int:
    path = args.path.rstrip("/") or "."
    repos = inst.config.repos
    try:
        if args.repo not in repos:
            raise ProjectInitError(
                f"no repo {args.repo!r} in abk.yaml (declared: {', '.join(repos)})"
            )
        if args.profile not in profiles.names():
            raise ProjectInitError(
                f"unknown profile {args.profile!r} (registered: {', '.join(profiles.names())})"
            )
        for existing in repos[args.repo].projects:
            if existing.path.rstrip("/") == path:
                raise ProjectInitError(
                    f"{args.repo} already registers {existing.path!r} (profile {existing.profile})"
                )
        config_file = inst.root / "abk.yaml"
        updated = add_entry(
            config_file.read_text(), args.repo, {"path": path, "profile": args.profile}
        )
    except ProjectInitError as error:
        print(f"abk: {error}", file=sys.stderr)
        return 1
    config_file.write_text(updated)
    print(f"registered {path} ({args.profile}) in {args.repo}")
    if args.scaffold:
        _scaffold(repos[args.repo].path / path, args.profile, Path(path).name)
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
