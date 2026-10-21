"""Starts the real agent command, forwards both directions unchanged and appends each line
the client sends to a file.

    python acp_recorder.py RECORD -- COMMAND [ARGS...]
"""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
from pathlib import Path


def wrapped(record: Path, command: list[str]) -> list[str]:
    """The argv that runs `command` under the recorder, writing to `record`."""
    return [sys.executable, str(Path(__file__).resolve()), str(record), "--", *command]


def main(argv: list[str]) -> int:
    record, separator, *command = argv
    if separator != "--" or not command:
        raise SystemExit("usage: acp_recorder.py RECORD -- COMMAND [ARGS...]")
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert child.stdin is not None and child.stdout is not None
    # One loop over both directions: no thread to join, and no line is held back.
    watching = selectors.DefaultSelector()
    watching.register(sys.stdin.fileno(), selectors.EVENT_READ, "client")
    watching.register(child.stdout.fileno(), selectors.EVENT_READ, "agent")
    with Path(record).open("ab") as out:
        while watching.get_map():
            for key, _ in watching.select():
                # Raw reads, so bytes the buffer already holds are never hidden from select.
                data = os.read(key.fd, 65536)
                if not data and key.data == "agent":
                    # The agent is gone: end here so the client sees EOF and the agent's code.
                    return child.wait()
                if not data:
                    watching.unregister(key.fd)
                    child.stdin.close()
                elif key.data == "client":
                    out.write(data)
                    out.flush()
                    try:
                        child.stdin.write(data)
                        child.stdin.flush()
                    except BrokenPipeError:
                        return child.wait()
                else:
                    os.write(sys.stdout.fileno(), data)
    return child.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
