"""`abk redact-history`: redact what was saved before values were redacted on the way in.

Temporary: removed once every installation with stored history has run it with `--apply`
and a second dry run finds nothing. It reads the files only; no code host is called.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from agent_build_kit import redaction
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import run_log_dir
from agent_build_kit.pipeline.transcript import transcript_dir
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME

HELP = "temporary: removed once every installation has run it"
COPY_SUFFIX = ".pre-redact"


def _saved_files(inst: Installation) -> list[Path]:
    state = inst.state_dir
    found = [state / "units.json", state / LEDGER_NAME]
    for directory in (run_log_dir(state), transcript_dir(state)):
        if directory.is_dir():
            found.extend(sorted(directory.iterdir()))
    return [p for p in found if p.is_file() and not p.name.endswith(COPY_SUFFIX)]


def _names_in(text: str, known: list[redaction.Source]) -> list[str]:
    return sorted(
        {
            s.name
            for s in known
            if s.value and len(s.value) >= redaction.MIN_LENGTH and s.value in text
        }
    )


def cmd_redact_history(args: argparse.Namespace, inst: Installation) -> int:
    redactor = redaction.gather(inst)
    known = redaction.sources(inst)
    for path in _saved_files(inst):
        text = path.read_text()
        clean = redactor.redact(text)
        if clean == text:
            continue
        names = _names_in(text, known) or ["token-shape"]
        print(f"{path}: {', '.join(names)}")
        if args.apply:
            shutil.copy2(path, path.with_name(path.name + COPY_SUFFIX))
            path.write_text(clean)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("redact-history", help=HELP, description=HELP)
    parser.add_argument("--apply", action="store_true", help="rewrite the files (default: dry run)")
    parser.set_defaults(func=cmd_redact_history)
