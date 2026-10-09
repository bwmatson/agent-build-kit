"""`abk attach release`: end a chat's attachment to a unit without the server."""

from __future__ import annotations

import argparse
import subprocess
from typing import Any

from agent_build_kit.cli.pipeline import branch_is_held
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import attach
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD


def cmd_attach_release(args: argparse.Namespace, inst: Installation) -> int:
    """Commit (`--commit MESSAGE`) or discard (`--discard`) the unit's uncommitted changes and
    release its lease in one operation; refuse a dirty tree given neither."""
    units = {u.id: u for u in UnitStore(inst.state_dir / "units.json").all()}
    if (unit := units.get(args.unit)) is None:
        print(f"abk attach release: no unit {args.unit!r}")
        return 2
    if args.commit is not None and args.discard:
        print("abk attach release: choose --commit or --discard, not both")
        return 2
    if unit.branch and branch_is_held(inst, unit.branch):
        print(f"{unit.id}: a step is running on the unit; nothing was changed")
        return 1
    files = attach.changes_of(inst, unit)
    if files and args.commit is None and not args.discard:
        print(
            f"{unit.id} holds {len(files)} uncommitted file(s): "
            "choose --commit MESSAGE to commit them or --discard to restore the tree"
        )
        return 1
    leases = attach.leases_of(inst)
    if args.discard:
        attach.discard(inst, unit)
        print(f"{unit.id}: discarded {len(files)} file(s); released")
    elif args.commit is not None and files:
        try:
            head = attach.commit(inst, unit, args.commit)
        except subprocess.CalledProcessError as error:
            output = (error.stdout or "") + (error.stderr or "")
            print(f"{unit.id}: the commit was rejected; the changes and the lease are kept")
            print(output.strip() or str(error))
            return 1
        print(f"{unit.id}: committed {head[:9]}; released")
    elif leases.attachment(unit.id) is None:
        print(f"{unit.id} is not attached")
    else:
        leases.drop(unit.id)
        print(f"{unit.id}: released")
    if unit.state == HELD and unit.cause is Cause.ATTACHED:
        print(f"{unit.id} is still held as attached: `abk requeue {unit.id}` gives it another go")
    return 0


def register(sub: Any) -> None:
    attach_parser = sub.add_parser("attach", help="a chat's attachment to a unit")
    verbs = attach_parser.add_subparsers(dest="attach_command", required=True)
    release = verbs.add_parser("release", help="commit or discard a unit's chat changes")
    release.add_argument("unit")
    release.add_argument("--commit", metavar="MESSAGE", default=None)
    release.add_argument("--discard", action="store_true")
    release.set_defaults(func=cmd_attach_release)
