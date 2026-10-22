"""`abk redact-history`: redact what was saved before values were redacted on the way in.

Temporary: removed once every installation with stored history has run it with `--apply`
and a second dry run finds nothing. It reads the files only; no code host is called.
"""

from __future__ import annotations

import argparse
import shutil
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

from agent_build_kit import redaction
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.original_copy import COPY_SUFFIX, copy_of
from agent_build_kit.pipeline.pause import paused_or_refused
from agent_build_kit.pipeline.run_log import run_log_dir
from agent_build_kit.pipeline.transcript import transcript_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, ledger_lock

HELP = "temporary: removed once every installation has run it"


def _saved_files(inst: Installation) -> list[Path]:
    state = inst.state_dir
    found = [state / "units.json", state / LEDGER_NAME]
    for directory in (run_log_dir(state), transcript_dir(state)):
        if directory.is_dir():
            found.extend(sorted(directory.iterdir()))
    return [p for p in found if p.is_file() and not p.name.endswith(COPY_SUFFIX)]


def _rewrite(path: Path, redactor: redaction.Redactor, *, apply: bool) -> None:
    """Report the names `path` holds and, when `apply`, replace them: the text read again
    where it is written, the original kept beside it, the new text written aside and
    renamed into place."""
    text = path.read_text()
    names = redactor.found(text)
    if not names:
        return
    print(f"{path}: {', '.join(names)}")
    if apply:
        shutil.copy2(path, copy_of(path))
        atomic_write_text(path, redactor.redact(text))


def _lock_of(inst: Installation, path: Path) -> AbstractContextManager[None]:
    """The lock the writers of `path` take; none for a file only appended to without one."""
    if path == inst.state_dir / "units.json":
        return UnitStore(path).locked()
    if path == inst.state_dir / LEDGER_NAME:
        return ledger_lock(path)
    return nullcontext()


def cmd_redact_history(args: argparse.Namespace, inst: Installation) -> int:
    if args.apply and not paused_or_refused(
        "redact-history --apply", inst, "a run log or transcript may be open"
    ):
        return 1
    redactor = redaction.gather(inst)
    for path in _saved_files(inst):
        with _lock_of(inst, path) if args.apply else nullcontext():
            _rewrite(path, redactor, apply=args.apply)
    if args.apply:
        print(
            f"the {COPY_SUFFIX} copies hold the original values: do not commit them; "
            "delete them when done"
        )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("redact-history", help=HELP, description=HELP)
    parser.add_argument("--apply", action="store_true", help="rewrite the files (default: dry run)")
    parser.set_defaults(func=cmd_redact_history)
