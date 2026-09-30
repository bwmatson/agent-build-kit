"""PreToolUse hook: apply the command policy to every Bash call, and keep file
writes inside the unit's worktree.

`command_policy` holds the rules; this carries the answer to Claude Code,
which runs it before each tool call — in headless runs and subagents too,
which is exactly where the unattended pipeline lives.

Two details of the contract shape this file:

- **A hook that errors fails open.** If this script crashes, or prints
  anything that isn't JSON, Claude Code records a non-blocking error and lets
  the call through. For a policy hook that default is backwards: a bug here
  would quietly re-enable `gh pr merge`. So every unexpected path denies.
- **stdout is parsed as a whole.** One stray line — a warning, a traceback, a
  leftover print — makes the entire output plain text and the decision is
  discarded. Nothing but the JSON may be printed.

Silence means "no objection", which leaves the normal permission flow in
charge. Answering `allow` would override the user's own deny rules, so this
never does.

Registered per run by `hook_settings`, as `<this interpreter> -m
agent_build_kit.hooks.policy --specs <dir>`: the interpreter running the
pipeline has the framework installed, and the specs directory is an argument
rather than something worked out from where this file sits.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_build_kit.pipeline.command_policy import check_command


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _branch_of(cwd: str) -> str | None:
    """The branch checked out in `cwd`, or None if there isn't one.

    `symbolic-ref` rather than `rev-parse --abbrev-ref`, because it answers on
    a branch with no commits yet — a freshly created unit branch, before its
    tests commit. A detached HEAD has no branch, so it returns None and the
    caller denies: the policy is branch-scoped and cannot be applied without
    one.
    """
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# Tools that write a file named by `file_path`.
FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def _checkout_of(path: Path) -> Path | None:
    """The git checkout `path` is in (it need not exist yet), or None."""
    existing = path
    while not existing.exists():
        if existing.parent == existing:
            return None
        existing = existing.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=existing if existing.is_dir() else existing.parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = result.stdout.strip()
    return Path(top).resolve() if top else None


def _check_file_write(payload: dict, specs: Path | None) -> dict | None:
    target = (payload.get("tool_input") or {}).get("file_path") or (
        payload.get("tool_input") or {}
    ).get("notebook_path")
    if not isinstance(target, str) or not target:
        return _deny("the policy hook could not read which file this would write")
    cwd = payload.get("cwd")
    path = (
        Path(target)
        if Path(target).is_absolute() or not isinstance(cwd, str)
        else Path(cwd) / target
    )
    path = path.resolve()
    # The specs agents build from, in the planning repo. Readable through
    # `--add-dir`, but not theirs to change: a build agent once ticked its own
    # tasks before review had seen them.
    if specs is not None and path.is_relative_to(specs.resolve()):
        return _deny(
            f"{target} is in the planning repo's specs, which are read-only for build "
            "agents; the pipeline marks tasks done once a unit has passed review"
        )

    # A unit's changes belong in its own worktree, where review and the PR
    # see them. An agent once edited a file in the user's own checkout of
    # another repo, which no commit picked up. Scratch files in the temp
    # directory are fine, as long as that isn't a way into another checkout.
    worktree = _checkout_of(Path(cwd)) if isinstance(cwd, str) else None
    if worktree is None:
        return _deny(
            f"the policy hook could not find the worktree this run is in (cwd {cwd!r}), "
            f"so it cannot tell whether writing {target} stays inside it"
        )
    if path.is_relative_to(worktree):
        return None
    if path.is_relative_to(Path(tempfile.gettempdir()).resolve()) and _checkout_of(path) is None:
        return None
    return _deny(
        f"{target} is outside this unit's worktree ({worktree}). Change only files in the "
        "worktree; if the change needs a file elsewhere (another repo, the user's own "
        "checkout), don't write it — report it as `BLOCKED: <what and where>` so a human "
        "can make it"
    )


def decide(
    payload: dict, *, specs: Path | None = None, planning_repo: Path | None = None
) -> dict | None:
    """The hook's answer: a deny decision, or None for "no objection"."""
    try:
        if payload.get("tool_name") in FILE_TOOLS:
            return _check_file_write(payload, specs)
        if payload.get("tool_name") != "Bash":
            return None

        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str) or not command.strip():
            return _deny("the policy hook could not read the command from the payload")

        cwd = payload.get("cwd")
        if not isinstance(cwd, str):
            return _deny("the policy hook could not read the working directory")

        branch = _branch_of(cwd)
        if branch is None:
            # The policy is branch-scoped — force-pushing is allowed on agent
            # branches and nowhere else — so without a branch it cannot be
            # applied, and guessing "allow" is how a guard gets bypassed.
            return _deny(
                f"the policy hook could not determine the branch in {cwd}, "
                "so it cannot tell whether this command is allowed there"
            )

        verdict = check_command(command, branch=branch)
        if verdict.allowed:
            return None
        return _deny(verdict.reason)
    except Exception as error:  # noqa: BLE001 — failing open is the danger here
        return _deny(f"the policy hook failed ({error!r}), so the command is refused")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--specs", type=Path, default=None)
    parser.add_argument("--branch-prefix", default=None)
    try:
        args = parser.parse_args(argv)
        if args.branch_prefix:
            # The hook is its own process: the prefix the policy scopes to has
            # to arrive as an argument, not from a workspace it never loaded.
            from agent_build_kit import config

            config.activate(
                config.active().model_copy(
                    update={"github": config.GithubConfig(branch_prefix=args.branch_prefix)}
                )
            )
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except Exception as error:  # noqa: BLE001
        print(json.dumps(_deny(f"the policy hook could not read its input ({error!r})")))
        return 0

    answer = decide(payload, specs=args.specs)
    if answer is not None:
        print(json.dumps(answer))
    return 0


def hook_settings(specs: Path | None, *, branch_prefix: str = "spec/") -> dict:
    """Settings that register this hook, for `claude -p --settings`.

    Passed per run rather than written into the user's global settings: the
    policy belongs to the unattended pipeline, not to the user's own sessions,
    and a global edit would apply to interactive work too — including denying
    `gh pr merge` when the user asked for it themselves.

    `specs` is the directory a build agent may read but not write; None for a
    run whose job is to write there (a proposal into the planning repo).
    """
    command = f"{sys.executable} -m agent_build_kit.hooks.policy --branch-prefix {branch_prefix}"
    if specs is not None:
        command += f" --specs {specs}"
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit",
                    "hooks": [{"type": "command", "command": command, "args": []}],
                }
            ]
        }
    }


if __name__ == "__main__":
    raise SystemExit(main())
