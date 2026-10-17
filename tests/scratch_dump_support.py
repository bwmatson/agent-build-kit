"""What the tests of the scratch-state dump share: a hand-made scratch filled the way a tick
leaves one, a stand-in tick, and a `pytester` run of generated live tests."""

from __future__ import annotations

import json
import re
import stat
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.lease import lease_dir
from agent_build_kit.pipeline.pause import PAUSE_MARKER
from agent_build_kit.pipeline.unit_store import HeldBy, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME
from tests import scratch_tick
from tests.factories import git, unit
from tests.scratch_fakes import HandScratch, hand_scratch
from tests.scratch_tick import TickResult, register_scratch, run_tick

BRANCH = "spec/feature/1"
PARENT = "parent/1"
FAILURE_NOTE = "the build step blew up"
HOLDER = "chat-session-7"
PAUSE_REASON = "wall of rate limit"
TICK_LINE = "TICK-OUTPUT-LINE"
TICK_EXIT = 4
REQUESTS = [
    ("GET", "/repos/example/app/pulls"),
    ("POST", "/repos/example/app/pulls"),
    ("GET", "/repos/example/app/issues/7/comments"),
]
SECTION_RULE = re.compile(r"^-+ SCRATCH STATE -+$")
PYTEST_BLOCK_END = re.compile(r"^(_{3,}|={3,})")


class RecordedHost:
    """A fake host that kept the requests it was sent, as the fake GitHub server does."""

    def __init__(self, requests: Sequence[tuple[str, str]]) -> None:
        self._requests = list(requests)

    def requests(self, method: str | None = None, path: str | None = None) -> list[tuple[str, str]]:
        return [
            r
            for r in self._requests
            if (method is None or r[0] == method) and (path is None or r[1] == path)
        ]


class DumpScratch(HandScratch):
    """A hand-made scratch that also has a host."""

    model_config = {"arbitrary_types_allowed": True}

    host: Any = None


def bare_scratch(
    tmp_path: Path, *, env: dict[str, str] | None = None, branch: str | None = BRANCH
) -> DumpScratch:
    """A scratch with a remote holding `main` and `branch`, an empty state directory and a
    host that recorded `REQUESTS`."""
    base = hand_scratch(tmp_path, branch=branch)
    base.planning.mkdir()
    return DumpScratch(
        planning=base.planning,
        remote=base.remote,
        state=base.state,
        env={"ABK_RUNTIME": "claude_code"} if env is None else env,
        host=RecordedHost(REQUESTS),
    )


def add_units(scratch: DumpScratch, ids: Iterable[str]) -> None:
    store = UnitStore(scratch.state / "units.json")
    store.upsert([unit(uid, change=uid.split("/")[0]) for uid in ids])


def add_decisions(scratch: DumpScratch, records: Iterable[tuple[str, str, Sequence[str]]]) -> None:
    """Decision-log records `(unit, reason, waits_on)`, oldest first."""
    lines = [
        json.dumps(
            {"at": "2026-01-01T00:00:00+00:00", "unit": u, "reason": r, "waits_on": list(on)}
        )
        for u, r, on in records
    ]
    with (scratch.state / DECISIONS_NAME).open("a") as handle:
        handle.writelines(line + "\n" for line in lines)


def add_ledger(scratch: DumpScratch, roles: Iterable[str]) -> None:
    rows = [
        {
            "kind": "agent",
            "at": "2026-01-01T00:00:00+00:00",
            "unit": "feature/1",
            "node": "implement",
            "role": role,
            "duration_ms": 1234,
        }
        for role in roles
    ]
    with (scratch.state / LEDGER_NAME).open("a") as handle:
        handle.writelines(json.dumps(row) + "\n" for row in rows)


def add_run_log(scratch: DumpScratch, lines: Iterable[str]) -> None:
    logs = scratch.state / "unit-logs"
    logs.mkdir(exist_ok=True)
    with (logs / "feature-01-run.log").open("a") as handle:
        handle.writelines(line + "\n" for line in lines)


def add_pause(scratch: DumpScratch, reason: str = PAUSE_REASON) -> None:
    (scratch.state / PAUSE_MARKER).write_text(
        json.dumps({"until": "2099-01-01T00:00:00+00:00", "reason": reason})
    )


def add_heads(scratch: DumpScratch, names: Iterable[str]) -> None:
    """Branches on the scratch's remote, all at `main`."""
    main = git(scratch.remote, "rev-parse", "main")
    for name in names:
        git(scratch.remote, "update-ref", f"refs/heads/{name}", main)


def filled_scratch(tmp_path: Path, *, env: dict[str, str] | None = None) -> DumpScratch:
    """What a tick leaves: a held unit and a failed one, their waits, a pause, a lease, a
    ledger and a run log, on a remote with two heads."""
    scratch = bare_scratch(tmp_path, env=env)
    add_units(scratch, ["feature/1", "feature/2"])
    store = UnitStore(scratch.state / "units.json")
    store.set_state("feature/1", HELD, branch=BRANCH, held_by=HeldBy.REVIEW)
    store.set_state("feature/2", FAILED, branch="spec/feature/2", note=FAILURE_NOTE)
    add_decisions(scratch, [("feature/1", "blocked", [PARENT]), ("feature/2", "backoff", [])])
    add_pause(scratch)
    add_ledger(scratch, ["implementer"])
    add_run_log(scratch, [f"run log line {number}" for number in range(1, 41)])
    leases = lease_dir(scratch.state)
    leases.mkdir()
    (leases / "feature--1.lease").write_text(
        json.dumps({"holder": HOLDER, "pid": 1, "started": "1"})
    )
    return scratch


def stand_in_tick(
    scratch: DumpScratch,
    monkeypatch: pytest.MonkeyPatch,
    lines: Sequence[str] = (TICK_LINE,),
    exit_code: int = TICK_EXIT,
) -> TickResult:
    """Run a tick in `scratch` whose `abk` prints `lines` and exits `exit_code`."""
    program = scratch.state.parent / "abk-stand-in"
    program.write_text(
        f"#!{sys.executable}\nfor line in {list(lines)!r}:\n    print(line)\n"
        f"raise SystemExit({exit_code})\n"
    )
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(scratch_tick, "ABK", program)
    return run_tick(scratch)


def ticked_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, env: dict[str, str] | None = None
) -> DumpScratch:
    """A filled scratch with one tick run and the scratch registered for the dump."""
    scratch = filled_scratch(tmp_path, env=env)
    stand_in_tick(scratch, monkeypatch)
    register_scratch(scratch)
    return scratch


def tree_state(root: Path) -> dict[Path, tuple[int, bytes]]:
    """Every path under `root` with its modification time and, for a file, its bytes."""
    return {
        path: (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else b"")
        for path in sorted(root.rglob("*"))
    }


PRELUDE = """\
import pytest

from tests.scratch_dump_support import *  # noqa: F403
"""


def run_children(pytester: pytest.Pytester, body: str, *, plugin: bool = True) -> pytest.RunResult:
    """Run generated live tests, with the dump plugin unless `plugin` is false."""
    pytester.makeini("[pytest]\nmarkers =\n    local_stack: a live test\n")
    pytester.makepyfile(test_child=PRELUDE + body)
    plugins = ["-p", "tests.scratch_dump"] if plugin else []
    return pytester.runpytest_inprocess(*plugins, "-p", "no:cacheprovider")


def sections(outlines: Sequence[str]) -> list[list[str]]:
    """The lines of each `SCRATCH STATE` section, up to the next failure block or summary."""
    found: list[list[str]] = []
    for index, line in enumerate(outlines):
        if not SECTION_RULE.match(line):
            continue
        body: list[str] = []
        for later in outlines[index + 1 :]:
            if PYTEST_BLOCK_END.match(later):
                break
            body.append(later)
        found.append(body)
    return found


def without_section(outlines: Sequence[str]) -> list[str]:
    """`outlines` with each `SCRATCH STATE` section dropped and the lines that vary by run
    (timing, header) removed."""
    kept: list[str] = []
    inside = False
    for line in outlines:
        if SECTION_RULE.match(line):
            inside = True
        elif inside and PYTEST_BLOCK_END.match(line):
            inside = False
        if inside or re.match(r"^(plugins|rootdir|configfile):", line):
            continue
        kept.append(re.sub(r" in \d+\.\d+s.*=", " =", line))
    return kept
