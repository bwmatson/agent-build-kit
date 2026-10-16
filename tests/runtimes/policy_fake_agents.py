"""Fake agents for the policy harness's tests, speaking the Agent Client Protocol over stdio.

Run as a real subprocess: `python policy_fake_agents.py RECORD MODE [--refuse PREFIX]
[--ask PREFIX] [--judge N] [--signal NAME] [--shell]`. The commands come from the inline code
span of each prompt. RECORD is a directory: the agent writes its pid and the pid of a child it
left in its process group (`agent.pid`, `child.pid`) before it imports anything heavy, and one
JSON line per thing it did to `did.jsonl`.

- `silent` never answers the first request.
- `judge` answers every prompt: a command starting with a `--refuse` prefix is left unasked
  (the agent's own deny list refused it), one starting with an `--ask` prefix asks permission
  first and asks the terminal only if allowed, any other asks the terminal. After `--judge N`
  prompts it stalls on the next without answering.
- `--signal NAME` has it send that signal to its parent on the first prompt, then stall.
- `--shell` has it ask the terminal for `sh -c <command>` instead of the command itself.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any


def command(record: Path, mode: str, *options: str) -> list[str]:
    """The argv that starts a fake agent recording to the directory `record`."""
    return [sys.executable, str(Path(__file__)), str(record), mode, *options]


def alive(pid: int) -> bool:
    """Whether the process exists and is not a zombie awaiting its reaper."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def still_alive(
    pids: Sequence[int], *, sleep: Callable[[float], None] = time.sleep, attempts: int = 200
) -> list[int]:
    """The pids still alive after giving a kill time to take effect: `alive` is asked up to
    `attempts` times, `sleep` called between asks, and the answer is those alive at the last."""
    raise NotImplementedError


def started(record: Path) -> bool:
    """Whether the fake has written both pid files."""
    return all((record / name).exists() for name in ("agent.pid", "child.pid"))


def pids(record: Path) -> list[int]:
    """The agent's own pid and the pid of the child it left in its group."""
    return [int((record / name).read_text()) for name in ("agent.pid", "child.pid")]


def did(record: Path) -> list[dict[str, Any]]:
    path = record / "did.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    parser.add_argument("mode", choices=["silent", "judge"])
    parser.add_argument("--refuse", action="append", default=[])
    parser.add_argument("--ask", action="append", default=[])
    parser.add_argument("--judge", type=int, default=10**6)
    parser.add_argument("--signal")
    parser.add_argument("--shell", action="store_true")
    args = parser.parse_args()
    child = subprocess.Popen(
        [sys.executable, "-c", "import threading; threading.Event().wait()"],
        stdin=subprocess.DEVNULL,
    )
    (args.record / "child.pid").write_text(str(child.pid))
    (args.record / "agent.pid").write_text(str(os.getpid()))
    # Imported only now, from this script's own directory: the protocol library is slow to load.
    importlib.import_module("policy_fake_agent_protocol").serve(args.record, args)


if __name__ == "__main__":
    main()
