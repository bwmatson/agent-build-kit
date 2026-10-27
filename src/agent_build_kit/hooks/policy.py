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
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_build_kit.pipeline.command_policy import (
    Verdict,
    check_command,
    check_no_commit,
    check_no_push,
    policy_files,
)
from agent_build_kit.pipeline.external_file import FILE_NAME as EXTERNAL_FILE
from agent_build_kit.pipeline.scratch import carries_scratch
from agent_build_kit.pipeline.tracker_file import FILE_NAME as TRACKER_FILE


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


def _check_file_write(
    payload: dict,
    specs: Path | None,
    planning_reports_dir: Path | None = None,
    planning_repo: Path | None = None,
    planning_change_dir: Path | None = None,
    planning_paths: tuple[str, ...] = (),
    confined: bool = False,
) -> dict | None:
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
    if not confined and specs is not None and path.is_relative_to(specs.resolve()):
        return _deny(
            f"{target} is in the planning repo's specs, which are read-only for build "
            "agents; the pipeline marks tasks done once a unit has passed review"
        )

    # The planning repo is fenced by path, not by checkout. A run that works
    # *in* it (the propose phase, which writes a change) has it as its own
    # checkout, and everything in one's own checkout is ordinarily one's to
    # write — including the tick's live state. So when this path belongs to the
    # planning repo's own git, only the run's log and tracker, and the one
    # change it was granted, are open; the rest is the pipeline's.
    #
    # "Belongs to its own git" and not merely "is beneath it": a code checkout
    # nested inside the planning repo is a checkout of its own.
    if planning_repo is not None and _checkout_of(path) == planning_repo.resolve():
        if _may_write_planning(path, planning_reports_dir, planning_change_dir):
            return None
        return _deny(
            f"{target} is in the planning repo, where this run may write only its run log "
            "and tracker under the state directory"
            + (" and the change it was asked to propose" if planning_change_dir else "")
            + ". The rest — the tick's live state, abk.yaml, the specs — is the pipeline's; "
            "if it needs changing, report it as `BLOCKED: <what and where>` so a human can make it"
        )

    # A unit's changes belong in its own worktree, where review and the PR
    # see them. An agent once edited a file in the user's own checkout of
    # another repo, which no commit picked up. Scratch files in the temp
    # directory are fine, as long as that isn't a way into another checkout.
    worktree = _checkout_of(Path(cwd)) if isinstance(cwd, str) else None
    if confined and worktree is not None and not path.is_relative_to(worktree):
        return None  # where a write may land is the sandbox's to say
    if worktree is None:
        return _deny(
            f"the policy hook could not find the worktree this run is in (cwd {cwd!r}), "
            f"so it cannot tell whether writing {target} stays inside it"
        )
    if path.is_relative_to(worktree):
        # A unit of the planning repo's own repository: the pipeline owns these paths.
        for fenced in planning_paths:
            if path.is_relative_to(worktree / fenced):
                return _deny(
                    f"{target} is a planning path ({fenced}), which the pipeline owns; "
                    "if it needs changing, report it as `BLOCKED: <what and where>` so a "
                    "human can make it"
                )
        return None
    # A track run's own bookkeeping: the Markdown run logs and tracker the
    # runner commits. The rest of the planning repo, including the tick's live
    # JSON state in the same directory, stays out of reach.
    if (
        planning_reports_dir is not None
        and path.suffix == ".md"
        and path.is_relative_to(planning_reports_dir.resolve())
    ):
        return None
    scratch = Path(tempfile.gettempdir()).resolve()
    # Scratch is the temp directory's own; a folder beside the run's checkout (where a
    # state directory may sit) is not.
    beside = worktree.parent if worktree.parent != scratch else None
    if (
        path.is_relative_to(scratch)
        and (beside is None or not path.is_relative_to(beside))
        and _checkout_of(path) is None
    ):
        return None
    return _deny(
        f"{target} is outside this unit's worktree ({worktree}). Change only files in the "
        "worktree; if the change needs a file elsewhere (another repo, the user's own "
        "checkout), don't write it — report it as `BLOCKED: <what and where>` so a human "
        "can make it"
    )


def _may_write_planning(
    path: Path, planning_reports_dir: Path | None, planning_change_dir: Path | None
) -> bool:
    """Whether a planning-repo path is one this run was granted.

    Its Markdown run log and tracker, which the runner commits — the rest of the
    state directory is the tick's live JSON, which a tick may be rewriting right
    now — and, for a propose run, anything under the one change it was asked to
    write.
    """
    if planning_reports_dir is not None:
        if path.suffix == ".md" and path.is_relative_to(planning_reports_dir.resolve()):
            return True
    if path.name in (EXTERNAL_FILE, TRACKER_FILE):
        # The holds and the tracker mapping of a change are the pipeline's to write, never an agent's.
        return False
    return planning_change_dir is not None and path.is_relative_to(planning_change_dir.resolve())


def decide(
    payload: dict,
    *,
    specs: Path | None = None,
    planning_repo: Path | None = None,
    planning_reports_dir: Path | None = None,
    planning_change_dir: Path | None = None,
    planning_paths: tuple[str, ...] = (),
    fenced_files: tuple[Path, ...] = (),
    protected_branches: tuple[str, ...] = (),
    no_push: bool = False,
    no_commit: bool = False,
    refusals_only: bool = False,
    confined: bool = False,
) -> dict | None:
    """The hook's answer: a deny decision, or None for "no objection"."""
    try:
        if refusals_only and payload.get("tool_name") != "Bash":
            return None
        if payload.get("tool_name") in FILE_TOOLS:
            return _check_file_write(
                payload,
                specs,
                planning_reports_dir,
                planning_repo,
                planning_change_dir,
                planning_paths,
                confined,
            )
        if payload.get("tool_name") != "Bash":
            return None

        command = (payload.get("tool_input") or {}).get("command")
        if not isinstance(command, str) or not command.strip():
            return _deny("the policy hook could not read the command from the payload")

        cwd = payload.get("cwd")
        if not isinstance(cwd, str):
            return _deny("the policy hook could not read the working directory")

        if refusals_only:
            verdict = Verdict(allowed=True)
            if no_push:
                verdict = check_no_push(command)
            if verdict.allowed and no_commit:
                verdict = check_no_commit(command)
            return None if verdict.allowed else _deny(verdict.reason)

        branch = _branch_of(cwd)
        if branch is None:
            # The policy is branch-scoped — force-pushing is allowed on agent
            # branches and nowhere else — so without a branch it cannot be
            # applied, and guessing "allow" is how a guard gets bypassed.
            return _deny(
                f"the policy hook could not determine the branch in {cwd}, "
                "so it cannot tell whether this command is allowed there"
            )

        # Only a checkout that carries a scratch folder is one a unit's run is in.
        checkout = _checkout_of(Path(cwd))
        if checkout is not None and not carries_scratch(checkout):
            checkout = None
        verdict = check_command(
            command,
            branch=branch,
            planning_repo=planning_repo,
            protected=protected_branches,
            worktree=checkout,
            cwd=Path(cwd).resolve(),
            fenced=policy_files(
                checkout=_checkout_of(Path(cwd)),
                planning_paths=planning_paths,
                planning_repo=planning_repo,
                fenced_files=fenced_files,
            ),
            confined=confined,
        )
        if verdict.allowed and no_push:
            verdict = check_no_push(command)
        if verdict.allowed and no_commit:
            verdict = check_no_commit(command)
        if verdict.allowed:
            return None
        return _deny(verdict.reason)
    except Exception as error:  # noqa: BLE001 — failing open is the danger here
        return _deny(f"the policy hook failed ({error!r}), so the command is refused")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--specs", type=Path, default=None)
    parser.add_argument("--branch-prefix", default=None)
    parser.add_argument("--planning-repo", type=Path, default=None)
    # `--planning-state-dir` is the flag's earlier name.
    parser.add_argument(
        "--planning-reports-dir",
        "--planning-state-dir",
        dest="planning_reports_dir",
        type=Path,
        default=None,
    )
    parser.add_argument("--planning-change-dir", type=Path, default=None)
    parser.add_argument("--planning-paths", default="")
    parser.add_argument("--fenced-file", type=Path, action="append", default=[])
    parser.add_argument("--protected-branches", default="")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--refusals-only", action="store_true")
    parser.add_argument("--confined", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.branch_prefix:
            # The hook is its own process: the prefix the policy scopes to has
            # to arrive as an argument, not from a workspace it never loaded.
            from agent_build_kit import config

            config.activate(
                config.active().model_copy(
                    update={"git": config.GitConfig(branch_prefix=args.branch_prefix)}
                )
            )
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except Exception as error:  # noqa: BLE001
        print(json.dumps(_deny(f"the policy hook could not read its input ({error!r})")))
        return 0

    answer = decide(
        payload,
        specs=args.specs,
        planning_repo=args.planning_repo,
        planning_reports_dir=args.planning_reports_dir,
        planning_change_dir=args.planning_change_dir,
        planning_paths=tuple(p for p in args.planning_paths.split(",") if p),
        fenced_files=tuple(args.fenced_file),
        protected_branches=tuple(b for b in args.protected_branches.split(",") if b),
        no_push=args.no_push,
        no_commit=args.no_commit,
        refusals_only=args.refusals_only,
        confined=args.confined,
    )
    if answer is not None:
        print(json.dumps(answer))
    return 0


def hook_settings(
    specs: Path | None,
    *,
    branch_prefix: str = "spec/",
    planning_repo: Path | None = None,
    planning_reports_dir: Path | None = None,
    planning_change_dir: Path | None = None,
    planning_paths: tuple[str, ...] = (),
    fenced_files: tuple[Path, ...] = (),
    protected_branches: tuple[str, ...] = (),
    no_push: bool = False,
    no_commit: bool = False,
    refusals_only: bool = False,
    confined: bool = False,
) -> dict:
    """Settings that register this hook, for `claude -p --settings`.

    Passed per run rather than written into the user's global settings: the
    policy belongs to the unattended pipeline, not to the user's own sessions,
    and a global edit would apply to interactive work too — including denying
    `gh pr merge` when the user asked for it themselves.

    `specs` is the directory a build agent may read but not write; None for a
    run whose job is to write there (a proposal into the planning repo).
    `planning_repo` is set for a track run: its branches are the pipeline's.
    `planning_reports_dir` is where in it that run may write its run log.
    `planning_change_dir` is the one change a propose run may write there.
    `planning_paths` are paths, relative to the unit's worktree, that a unit of the planning
    repo's own repository may not write: the pipeline owns them.
    `fenced_files` are files no command may write, the planning repo's abk.yaml among them.
    `protected_branches` are the branches repos integrate on beyond `main` and
    `master`, which a direct push is refused to; the hook is its own process and
    knows no workspace, so it has to be told.
    `no_commit` refuses every `git commit`: a chat turn leaves its changes in the tree
    for the person to commit. `refusals_only` leaves out everything else the hook
    enforces, for a session that is the person's own.
    `no_push` refuses every `git push`, as the acp broker does: a unit run never
    pushes, the pipeline does, and a push is refused before it runs rather than
    found after.
    `confined` stands down the location guards the kernel repeats (the worktree check and the
    specs fence on file writes, the planning repo's configuration fence on commands); the
    guards about meaning stay.
    """
    command = f"{sys.executable} -m agent_build_kit.hooks.policy --branch-prefix {branch_prefix}"
    if specs is not None:
        command += f" --specs {shlex.quote(str(specs))}"
    if planning_repo is not None:
        command += f" --planning-repo {shlex.quote(str(planning_repo))}"
    if planning_reports_dir is not None:
        command += f" --planning-reports-dir {shlex.quote(str(planning_reports_dir))}"
    if planning_change_dir is not None:
        command += f" --planning-change-dir {shlex.quote(str(planning_change_dir))}"
    if planning_paths:
        command += " --planning-paths " + shlex.quote(",".join(planning_paths))
    for fenced in fenced_files:
        command += f" --fenced-file {shlex.quote(str(fenced))}"
    if protected_branches:
        command += f" --protected-branches {','.join(protected_branches)}"
    if no_push:
        command += " --no-push"
    if no_commit:
        command += " --no-commit"
    if refusals_only:
        command += " --refusals-only"
    if confined:
        command += " --confined"
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
