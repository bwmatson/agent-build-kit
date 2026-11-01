"""`abk external`: hand work to someone outside the kit, record its merge, or take it back.

The holds live in each change's `external.yaml` (spec: external-work); every command here has a
`--json` form and is safe to repeat.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit.cli.pipeline import store_for
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_done import HandMergeRefused, record_hand_merge
from agent_build_kit.pipeline.external_file import (
    Hold,
    HoldRefused,
    add_hold,
    already_held,
    check_not_started,
    hold_rows,
    hold_text,
    release_all,
    release_holds,
)


def _items(pairs: list[str]) -> dict[str, str | list[str]]:
    """`key=value` pairs; a key given again collects its values into a list."""
    items: dict[str, str | list[str]] = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if not key or not value:
            raise HoldRefused(f"--item {pair!r} is not key=value")
        held = items.get(key)
        if held is None:
            items[key] = value
        else:
            items[key] = [*([held] if isinstance(held, str) else held), value]
    return items


def _emit(args: argparse.Namespace, payload: dict[str, Any], text: str) -> None:
    print(json.dumps(payload) if args.json else text)


def _change_folder(inst: Installation, change: str) -> Path:
    """The folder of an existing change (`openspec new change` makes it before a hold)."""
    folder = inst.changes_dir / change
    if not folder.is_dir():
        raise HoldRefused(f"change {change} does not exist")
    return folder


def _refusing(args: argparse.Namespace, name: str, run: Callable[[], int]) -> int:
    try:
        return run()
    except (HoldRefused, HandMergeRefused) as error:
        print(f"abk external {name}: refused: {error}", file=sys.stderr)
        if args.json:
            print(json.dumps({"refused": str(error)}))
        return 1


def cmd_hand_off(args: argparse.Namespace, inst: Installation) -> int:
    def run() -> int:
        change_dir = _change_folder(inst, args.change)
        scope = tuple(sorted(set(args.groups))) if args.groups else "all"
        hold = Hold(
            scope=scope,
            holder=args.holder,
            link=args.link,
            since=datetime.now(UTC),
            items=_items(args.item),
            note=args.note,
        )
        groups = list(scope) if args.groups else "all"
        same = already_held(change_dir, hold)
        if not same:
            check_not_started(change_dir, hold, store_for(inst).all())
            add_hold(change_dir, hold)
        payload = {
            "change": args.change,
            "groups": groups,
            "holder": args.holder,
            "link": args.link,
            "already_held": same,
        }
        shown = ", ".join(map(str, scope)) if args.groups else "all"
        text = (
            f"{args.change} groups {shown} already held by {args.holder}: nothing changed"
            if same
            else f"{args.change} groups {shown} handed to {args.holder}"
        )
        _emit(args, payload, text)
        return 0

    return _refusing(args, "hand-off", run)


def cmd_list(args: argparse.Namespace, inst: Installation) -> int:
    rows = hold_rows(inst.changes_dir, store_for(inst).all(), datetime.now(UTC))
    if args.json:
        print(json.dumps({"holds": [row.model_dump(mode="json") for row in rows]}))
    elif not rows:
        print("no holds")
    else:
        for row in rows:
            print(hold_text(row))
    return 0


def cmd_done(args: argparse.Namespace, inst: Installation) -> int:
    def run() -> int:
        record_hand_merge(
            inst, store_for(inst), args.change, args.groups, pr=args.pr, commit=args.commit
        )
        merged_by = str(args.pr) if args.pr is not None else args.commit
        payload = {"change": args.change, "groups": list(args.groups), "merged_by": merged_by}
        shown = ", ".join(map(str, args.groups))
        _emit(args, payload, f"{args.change} groups {shown} recorded as merged by {merged_by}")
        return 0

    return _refusing(args, "done", run)


def cmd_release(args: argparse.Namespace, inst: Installation) -> int:
    def run() -> int:
        folder = _change_folder(inst, args.change)
        freed = release_all(folder) if args.all else release_holds(folder, args.groups)
        shown = f"groups {', '.join(map(str, freed))}" if freed else "all"
        _emit(
            args,
            {"change": args.change, "groups": list(freed)},
            f"{args.change} {shown} released to the kit",
        )
        return 0

    return _refusing(args, "release", run)


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("external", help="work handed to someone outside the kit")
    actions = parser.add_subparsers(dest="external_command", required=True)

    def command(name: str, help: str, func: Callable[..., int]) -> argparse.ArgumentParser:
        added = actions.add_parser(name, help=help)
        added.add_argument("--json", action="store_true", help="print one JSON document")
        added.set_defaults(func=func)
        return added

    hand = command("hand-off", "hand a change or some of its groups to someone", cmd_hand_off)
    hand.add_argument("change")
    scope = hand.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--all", action="store_true", help="the whole change, groups added later too"
    )
    scope.add_argument("--groups", type=int, nargs="+", help="the group numbers handed over")
    hand.add_argument("--holder", required=True, help="who takes it (a display name)")
    hand.add_argument("--link", required=True, help="the board item or issue")
    hand.add_argument("--item", action="append", default=[], help="a board item id, key=value")
    hand.add_argument("--note", default="", help="why")

    command("list", "show every hold and the units waiting on it", cmd_list)

    done = command("done", "record that handed-off work is merged", cmd_done)
    done.add_argument("change")
    done.add_argument("--groups", type=int, nargs="+", required=True)
    source = done.add_mutually_exclusive_group(required=True)
    source.add_argument("--pr", type=int, help="a pull request the forge reports merged")
    source.add_argument("--commit", help="a commit on the default branch")

    release = command("release", "give held work back to the kit", cmd_release)
    release.add_argument("change")
    which = release.add_mutually_exclusive_group(required=True)
    which.add_argument("--groups", type=int, nargs="+", help="the group numbers given back")
    which.add_argument(
        "--all",
        action="store_true",
        help="every hold still held, also of a change with no groups yet",
    )
