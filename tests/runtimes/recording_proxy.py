"""A transparent stand between a client and a real agent, writing down what each said.

    python recording_proxy.py RECORD COMMAND [ARG ...]

Runs COMMAND with this process's stdin and stdout as its own, passing every line through
unchanged and appending it to RECORD as one JSON line naming who sent it (`client` or
`agent`) and the message, so a test can say which requests an agent was sent and what it
answered, whatever the agent is.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path


def note(record: Path, who: str, line: bytes, lock: threading.Lock) -> None:
    try:
        message = json.loads(line)
    except ValueError:
        message = line.decode(errors="replace")
    with lock, record.open("a") as out:
        out.write(json.dumps({"from": who, "message": message}) + "\n")


def main() -> int:
    record = Path(sys.argv[1])
    child = subprocess.Popen(sys.argv[2:], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert child.stdin is not None and child.stdout is not None
    lock = threading.Lock()

    def answers() -> None:
        assert child.stdout is not None
        for line in child.stdout:
            note(record, "agent", line, lock)
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

    pump = threading.Thread(target=answers)
    pump.start()
    try:
        for line in sys.stdin.buffer:
            note(record, "client", line, lock)
            child.stdin.write(line)
            child.stdin.flush()
    except BrokenPipeError:
        pass
    finally:
        child.stdin.close()
        returncode = child.wait()
        pump.join()
    return returncode


if __name__ == "__main__":
    sys.exit(main())
