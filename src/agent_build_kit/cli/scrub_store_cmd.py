"""`abk scrub-store`: replace home-directory paths in the stored unit text.

Only home prefixes go, each replaced by `<home>/`; other terms stay, because a repo name in
a unit's feedback is the record's own subject."""

from __future__ import annotations

import argparse
import re
import shutil
from collections.abc import Iterator

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.original_copy import copy_of
from agent_build_kit.pipeline.pause import paused_or_refused
from agent_build_kit.pipeline.unit_store import REWRITTEN_TEXT_FIELDS, UnitStore
from agent_build_kit.scrub_terms import ROOT_HOME, TILDE_HOME, TOOL_DIRS

HELP = "replace home-directory paths in the stored unit text"
HOME_TOKEN = "<home>/"
_TOOLS = "|".join(re.escape(d) for d in sorted(TOOL_DIRS))
# A home root and a user directory, or a tilde-slash prefix followed by a directory the tool
# allowance does not name. The user directory is name characters only, so punctuation after a
# bare one stays.
HOME_PREFIX = re.compile(rf"{ROOT_HOME}[\w.-]+/?|{TILDE_HOME}(?!(?:{_TOOLS})\b)")


def scrub_home_paths(text: str) -> str:
    return HOME_PREFIX.sub(HOME_TOKEN, text)


def _counts(store: UnitStore) -> Iterator[tuple[str, str, int]]:
    """Each record's count of home paths per field, the history notes summed in one row."""
    for unit in store.all():
        for field in REWRITTEN_TEXT_FIELDS:
            yield unit.id, field, len(HOME_PREFIX.findall(getattr(unit, field)))
        notes = (entry.get("note") for entry in unit.history)
        yield (
            unit.id,
            "history note",
            sum(len(HOME_PREFIX.findall(note)) for note in notes if isinstance(note, str)),
        )


def cmd_scrub_store(args: argparse.Namespace, inst: Installation) -> int:
    if args.apply and not paused_or_refused(
        "scrub-store --apply", inst, "a run may be writing the store"
    ):
        return 1
    store = UnitStore(inst.state_dir / "units.json")
    found = [(uid, field, n) for uid, field, n in _counts(store) if n]
    for uid, field, n in found:
        print(f"{uid} {field}: {n} path(s)")
    if not found:
        print("nothing found: no home-directory path in the stored text")
    elif args.apply:
        copy = copy_of(store.path)
        if not copy.exists():
            shutil.copy2(store.path, copy)
        store.rewrite_text(scrub_home_paths)
        print(f"{copy.name} holds the original: do not commit it; delete it when done")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("scrub-store", help=HELP, description=HELP)
    parser.add_argument("--apply", action="store_true", help="rewrite the store (default: dry run)")
    parser.set_defaults(func=cmd_scrub_store)
