"""`abk manual raise`: a builder registers a step only a person can do, with a check script.

The script lives under `.abk/manual/` in the unit's worktree and is never committed. The command
validates it (it exists, is executable and finishes within the timeout), registers the step on the
unit whose branch the worktree is on, and never marks the step done: the tick decides that.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from agent_build_kit.cli.install_config import Refused, worktree_root
from agent_build_kit.cli.pipeline import evaluate_manual_waits, store_for
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.manual_steps import MANUAL_FOLDER, unmet_steps
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import BUILDS_NOTHING, FINISHED_STATES, ManualStep


def _unit_id(worktree: Path, prefix: str) -> str:
    branch = git(worktree, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    if not branch.startswith(prefix):
        raise Refused(f"the worktree is on `{branch}`, not on a unit's {prefix}<change>/<n>")
    return branch.removeprefix(prefix)


def _script(worktree: Path, check: str) -> Path:
    path = worktree / check
    folder = worktree / MANUAL_FOLDER
    if path.is_symlink() or not path.resolve().is_relative_to(folder):
        raise Refused(f"{check} is not a file under {MANUAL_FOLDER}/ of this worktree")
    if not path.is_file():
        raise Refused(f"{check} does not exist")
    if not os.access(path, os.X_OK):
        raise Refused(f"{check} is not executable")
    return path.resolve()


def _runs_in_time(script: Path, worktree: Path, seconds: int) -> None:
    try:
        subprocess.run(
            [str(script)],
            cwd=worktree,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise Refused(f"{script.name} ran past the timeout of {seconds} seconds") from error
    except OSError as error:
        raise Refused(f"{script.name} could not run: {error}") from error


def cmd_manual_raise(args: argparse.Namespace, inst: Installation) -> int:
    try:
        worktree = worktree_root()
        unit_id = _unit_id(worktree, inst.config.git.branch_prefix)
        store = store_for(inst)
        try:
            held = store.get(unit_id)
        except KeyError:
            raise Refused(f"no unit {unit_id} in the store") from None
        if any(step.slug == args.slug for step in held.manual_steps):
            raise Refused(f"unit {unit_id} already has a step `{args.slug}`")
        script = _script(worktree, args.check)
        _runs_in_time(script, worktree, inst.config.global_limits.manual_check_seconds)
        step = ManualStep(slug=args.slug, text=args.text, check=args.check)
        store.set_manual_steps(unit_id, (*held.manual_steps, step))
    except Refused as error:
        print(f"abk manual raise: refused: {error}", file=sys.stderr)
        return 1
    print(f"abk manual raise: step {args.slug} registered on {unit_id}")
    return 0


def cmd_manual_check(args: argparse.Namespace, inst: Installation) -> int:
    """Run the checks of the outstanding steps now, as a tick pass does."""
    store = store_for(inst)
    if args.slug and not any(
        step.slug == args.slug and not step.done
        for unit in store.all()
        for step in unit.manual_steps
    ):
        print(f"abk manual check: no outstanding step `{args.slug}`", file=sys.stderr)
        return 1
    evaluate_manual_waits(inst, store, slug=args.slug)
    return 0


def _outstanding(unit: StoredUnit) -> list[ManualStep]:
    """The unmet steps of a unit the tick still checks; a unit that builds nothing or has
    finished waits on none."""
    if unit.state in (*BUILDS_NOTHING, *FINISHED_STATES):
        return []
    return unmet_steps(unit)


def cmd_manual_list(args: argparse.Namespace, inst: Installation) -> int:
    """List the steps a person has to do, or with `--done` the finished ones too."""
    rows = [
        (unit, step)
        for unit in store_for(inst).all()
        for step in (unit.manual_steps if args.done else _outstanding(unit))
    ]
    if not rows:
        print("no manual steps outstanding")
        return 0
    for unit, step in rows:
        print(f"{unit.id}  {step.slug}{'  (done)' if step.done else ''}: {step.text}")
        if step.runbook:
            print(f"  runbook: {step.runbook}")
        if step.outcome:
            when = f" at {step.checked_at.isoformat()}" if step.checked_at else ""
            print(f"  last check{when}: {step.outcome}: {step.last_line}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("manual", help="steps only a person can do, checked by the tick")
    actions = parser.add_subparsers(dest="manual_command", required=True)
    raised = actions.add_parser("raise", help="register a step with a check script")
    raised.add_argument("slug", help="a name for the step, unique within the unit")
    raised.add_argument("--text", required=True, help="what a person does")
    raised.add_argument("--check", required=True, help="a script under .abk/manual/")
    raised.set_defaults(func=cmd_manual_raise)
    checked = actions.add_parser("check", help="run the checks of the outstanding steps now")
    checked.add_argument("slug", nargs="?", default="", help="only the step with this name")
    checked.set_defaults(func=cmd_manual_check)
    listed = actions.add_parser("list", help="list the steps a person has to do")
    listed.add_argument("--done", action="store_true", help="include the finished steps")
    listed.set_defaults(func=cmd_manual_list)
