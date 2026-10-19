"""Records what a Claude Code run is sent, then becomes `claude` itself.

    python claude_recorder.py RECORD -- COMMAND [ARGS...]

Set as `runtimes.claude_code.command` (through `wrapped`), the pipeline appends its own
arguments to COMMAND. The wrapper appends a header line with the arguments to RECORD, and for a
`-p` run the standard input the prompt arrives on, then ends the record with a newline of its own.
It then replaces itself with COMMAND by `exec`, handing it the same arguments and the same input
through a file, so no process of the wrapper's is left and the process arguments are Claude's.
A run that is not `-p` (a login or status check) leaves its standard input alone.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HEADER = "\x00abk-run "
PROMPT_FLAG = "-p"


def wrapped(record: Path, command: list[str]) -> list[str]:
    """The argv that runs `command` under the recorder, writing to `record`."""
    return [sys.executable, str(Path(__file__).resolve()), str(record), "--", *command]


def main(argv: list[str]) -> None:
    record, separator, *command = argv
    if separator != "--" or not command:
        raise SystemExit("usage: claude_recorder.py RECORD -- COMMAND [ARGS...]")
    header = (HEADER + json.dumps(command) + "\n").encode()
    if PROMPT_FLAG not in command:
        _append(Path(record), header)
        os.execvp(command[0], command)
    prompt = sys.stdin.buffer.read()
    _append(Path(record), header + prompt + b"\n")
    handed_on = tempfile.TemporaryFile()
    handed_on.write(prompt)
    handed_on.seek(0)
    os.dup2(handed_on.fileno(), 0)
    os.execvp(command[0], command)


def _append(record: Path, blob: bytes) -> None:
    """One write, so runs that overlap do not interleave their records."""
    with record.open("ab") as out:
        out.write(blob)


if __name__ == "__main__":
    main(sys.argv[1:])
