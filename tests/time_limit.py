"""A pytest plugin that fails a test which runs past a time limit, from a thread.

The limit, on each of a test's setup, call and teardown, is a CPU budget (the CPU time of
the process and its children) of `--test-time-limit` seconds (default
`DEFAULT_TEST_TIME_LIMIT`), with a wall-clock backstop of `time_limit_backstop_factor` times it
(an ini setting, defaulting to `BACKSTOP_FACTOR`). A
test with the `e2e` (e2e-test) marker has `--e2e-test-time-limit` seconds of wall
time (default `DEFAULT_E2E_TEST_TIME_LIMIT`) and no CPU budget; a test marked
`time_limit(<seconds>)` gets that budget in place of the first; zero turns a limit off. A
watcher thread polls the CPU and a timer the wall clock, and each signals the main thread
when its budget passes, which interrupts the test wherever it is, including in a blocking
call. The test fails (or errors, in setup or teardown) naming the clock that fired and the
run goes on.
"""

from __future__ import annotations

import faulthandler
import json
import os
import signal
import sys
import tempfile
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Collection, Mapping
from pathlib import Path

import pytest

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.pipeline.run_log import TEST_TRACE_VARIABLE

DEFAULT_TEST_TIME_LIMIT = 60
# For a test whose work (a repo scan, a unit-graph pass) takes several times longer when loaded.
LOADED_TEST_TIME_LIMIT = DEFAULT_TEST_TIME_LIMIT * 5
DEFAULT_E2E_TEST_TIME_LIMIT = 30 * 60
# The wall-clock backstop is this many times the CPU budget.
BACKSTOP_FACTOR: int = 5


class Budget(Frozen):
    """What a phase may use: CPU seconds of the process and its children, and wall seconds
    as a backstop; zero turns a clock off."""

    cpu: float
    wall: float


def budget_for(item: pytest.Item) -> Budget:
    """The budgets of a test's setup, call or teardown: its limit as CPU seconds with a wall
    backstop of the `time_limit_backstop_factor` ini setting times it (default `BACKSTOP_FACTOR`);
    an e2e test has only its wall limit."""
    limit = max(limit_for(item), 0)
    if item.get_closest_marker("e2e") is not None:
        return Budget(cpu=0, wall=limit)
    factor = float(item.config.getini("time_limit_backstop_factor"))
    return Budget(cpu=limit, wall=limit * factor)


def clock_fired(budget: Budget, cpu_used: float, wall_elapsed: float) -> str | None:
    """ "cpu" or "wall" once that clock passes its budget, else None."""
    if budget.cpu > 0 and cpu_used > budget.cpu:
        return "cpu"
    if budget.wall > 0 and wall_elapsed > budget.wall:
        return "wall"
    return None


def exceeded_text(clock: str, budget: Budget) -> str:
    """The failure sentence that names the clock that fired."""
    if clock == "cpu":
        return f"exceeded the CPU time budget of {budget.cpu:g} s"
    return f"exceeded the wall-clock backstop of {budget.wall:g} s"


POLL_SECONDS = 0.25
_TICKS = os.sysconf("SC_CLK_TCK")


def _stat_fields(pid: int | str) -> list[str]:
    """The fields of /proc/<pid>/stat after the command name, which sits in parentheses and may
    hold spaces; `pid` may be a path such as `self/task/<tid>`. Raises OSError for a process
    that has gone."""
    with open(f"/proc/{pid}/stat") as stat:
        text = stat.read()
    return text[text.rindex(")") + 2 :].split()


def _spent(fields: list[str]) -> float:
    """utime, stime and what the process collected from its finished children (cutime, cstime)."""
    return sum(int(value) for value in fields[11:15]) / _TICKS


def _child_pids(pid: int) -> list[int]:
    """The direct children of a process, from /proc/<pid>/task/*/children; none for a process
    that has gone."""
    found: list[int] = []
    try:
        for task in os.listdir(f"/proc/{pid}/task"):
            with open(f"/proc/{pid}/task/{task}/children") as children:
                found.extend(int(child) for child in children.read().split())
    except OSError:
        pass
    return found


def _scan_descendants() -> list[tuple[int, list[str]]]:
    """The descendants for a kernel without per-task children files: every process is read."""
    children: dict[int, list[tuple[int, list[str]]]] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            fields = _stat_fields(name)
        except OSError:
            continue
        children.setdefault(int(fields[1]), []).append((int(name), fields))
    found: list[tuple[int, list[str]]] = []
    pending = [os.getpid()]
    while pending:
        for pid, fields in children.get(pending.pop(), []):
            found.append((pid, fields))
            pending.append(pid)
    return found


def running_descendants() -> list[tuple[int, list[str]]]:
    """Each running descendant of the process as (pid, the fields of its /proc stat), found by
    the children files, or by reading every process on a kernel that has none. A host without
    /proc has none."""
    me = os.getpid()
    try:
        if not os.path.exists(f"/proc/{me}/task/{me}/children"):
            return _scan_descendants()
        found: list[tuple[int, list[str]]] = []
        pending = _child_pids(me)
        while pending:
            pid = pending.pop()
            try:
                found.append((pid, _stat_fields(pid)))
            except OSError:
                continue
            pending.extend(_child_pids(pid))
        return found
    except OSError:
        return []


def descendants_cpu() -> dict[int, float]:
    """Process id to CPU seconds, from /proc, of each running descendant, including what it has
    already collected from its own finished children. Only descendants are read, so a test with
    no children costs one small read. A host without /proc has none."""
    return {pid: _spent(fields) for pid, fields in running_descendants()}


def running_children() -> str:
    """One line per running descendant of the process: its command line and how long it has
    run, from /proc. Empty when there is none or the host has no /proc."""
    lines: list[str] = []
    try:
        with open("/proc/uptime") as uptime:
            now = float(uptime.read().split()[0])
        for pid, fields in running_descendants():
            try:
                started = int(fields[19]) / _TICKS
                with open(f"/proc/{pid}/cmdline", "rb") as cmdline:
                    command = cmdline.read().replace(b"\0", b" ").decode(errors="replace").strip()
            except (OSError, IndexError, ValueError):
                continue
            lines.append(f"{command} (pid {pid}), running for {max(0.0, now - started):.1f} s")
    except (OSError, ValueError, IndexError):
        return ""
    return "\n".join(sorted(lines))


def live_descendants_cpu() -> float:
    """CPU seconds, from /proc, of the process's running descendants (see `descendants_cpu`)."""
    return sum(descendants_cpu().values())


def read_cpu() -> float:
    """CPU seconds used so far by this process and its children, finished or running."""
    times = os.times()
    finished = times.children_user + times.children_system
    return time.process_time() + finished + live_descendants_cpu()


class CpuSnapshot(Frozen):
    """One reading of the CPU in use: the whole process's seconds (every thread, exited ones
    included), each thread other than the main one by task id, each running descendant by
    process id, and what the process has collected from finished children."""

    process: float
    tasks: dict[int, float]
    descendants: dict[int, float]
    reaped: float
    children: frozenset[int] = frozenset()


def _task_cpu(tid: int | str) -> float:
    """utime and stime of one thread of this process, in seconds."""
    fields = _stat_fields(f"self/task/{tid}")
    return (int(fields[11]) + int(fields[12])) / _TICKS


def snapshot_cpu() -> CpuSnapshot:
    """Read the CPU now. A host without /proc/self/task has only the whole process's reading."""
    times = os.times()
    reaped = times.children_user + times.children_system
    process = time.process_time()
    if not os.path.isdir("/proc/self/task"):
        return CpuSnapshot(process=process, tasks={}, descendants={}, reaped=reaped)
    tasks: dict[int, float] = {}
    for name in os.listdir("/proc/self/task"):
        try:
            tasks[int(name)] = _task_cpu(name)
        except OSError:
            continue
    tasks.pop(os.getpid(), None)
    running = running_descendants()
    me = str(os.getpid())
    return CpuSnapshot(
        process=process,
        tasks=tasks,
        descendants={pid: _spent(fields) for pid, fields in running},
        reaped=reaped,
        children=frozenset(pid for pid, fields in running if fields[1] == me),
    )


class CpuTerms(Frozen):
    """The terms a phase's billed CPU is made of, in seconds."""

    process: float
    inherited: float
    own: float
    new_children: float
    reaped: float

    @property
    def total(self) -> float:
        return self.process - self.inherited - self.own + self.new_children + self.reaped


def phase_cpu_terms(start: CpuSnapshot, now: CpuSnapshot, own: Collection[int] = ()) -> CpuTerms:
    """The terms of `phase_cpu`: the process's growth (threads that started and ended in the
    phase included), the growth of each thread in `start` that is still alive, the whole of each
    new thread in `own` (the plugin's own), all of each descendant not in `start`, and the
    growth of what finished children gave less what a direct child of `start` had already used
    when it was reaped in the phase."""
    inherited = sum(v - start.tasks[tid] for tid, v in now.tasks.items() if tid in start.tasks)
    watching = sum(v for tid, v in now.tasks.items() if tid in own and tid not in start.tasks)
    new_descendants = sum(v for pid, v in now.descendants.items() if pid not in start.descendants)
    before_phase = sum(
        start.descendants[pid]
        for pid in start.children
        if pid in start.descendants and pid not in now.descendants
    )
    return CpuTerms(
        process=now.process - start.process,
        inherited=inherited,
        own=watching,
        new_children=new_descendants,
        reaped=max(0.0, now.reaped - start.reaped - before_phase),
    )


def phase_cpu(start: CpuSnapshot, now: CpuSnapshot, own: Collection[int] = ()) -> float:
    """The CPU a phase used: the process's growth (threads that started and ended in the phase
    included) less the growth of each thread in `start` that is still alive and the whole of each
    new thread in `own` (the plugin's own), plus all of each descendant not in `start`, plus the
    growth of what finished children gave, less what a direct child of `start` had already used
    when it was reaped in the phase. An inherited thread that exits during the phase is still
    billed for its last moments."""
    return phase_cpu_terms(start, now, own).total


# What each phase left alive: task id or process id to (its name, the test that left it).
LEFT_BY: dict[int, tuple[str, str]] = {}


def record_left(start: CpuSnapshot, now: CpuSnapshot, nodeid: str) -> None:
    """Record, under `nodeid`, each thread and descendant alive in `now` and not in `start`;
    forget every record whose id is gone, since an id may be reused."""
    alive = set(now.tasks) | set(now.descendants)
    for gone in set(LEFT_BY) - alive:
        del LEFT_BY[gone]
    names = {t.native_id: t.name for t in threading.enumerate()}
    for tid in now.tasks:
        if tid not in start.tasks:
            LEFT_BY.setdefault(tid, (f"thread {names.get(tid, 'unnamed')}", nodeid))
    for pid in now.descendants:
        if pid not in start.descendants:
            LEFT_BY.setdefault(pid, ("child process", nodeid))


def left_by_of(left_by: Mapping[int, tuple[str, str]], kind: str, ident: int) -> tuple[str, str]:
    """The name of a thread or descendant and the test that left it running, or a name made of
    its kind and id and `an earlier test`."""
    return left_by.get(ident, (f"{kind} {ident}", "an earlier test"))


def inherited_lines(
    start: CpuSnapshot, now: CpuSnapshot, left_by: dict[int, tuple[str, str]]
) -> list[str]:
    """One line for each thread or descendant alive at `start` that used CPU by `now`: its name,
    the test that left it, and its seconds."""
    lines: list[str] = []
    for kind, before, after in (
        ("task", start.tasks, now.tasks),
        ("process", start.descendants, now.descendants),
    ):
        for ident, was in before.items():
            grew = after.get(ident, was) - was
            if grew <= 0:
                continue
            name, test = left_by_of(left_by, kind, ident)
            lines.append(
                f"{name} ({kind} {ident}), left running by {test}, used {grew:.2f} s of CPU "
                "in this phase"
            )
    return lines


# A phase over this many wall seconds is always written to the trace file.
SLOW_PHASE_SECONDS = 5.0
# The entries a worker keeps in memory, and how many of them a trip writes.
TRACE_KEPT = 200
TRIP_ENTRIES = 30
# The errors after a trip whose full traceback is written.
TRACED_ERRORS = 2


class PhaseEntry(Frozen):
    """One phase of one test: its id and phase, wall seconds, the process's CPU seconds in it,
    the live thread and child counts at its end and the one-minute load."""

    test: str
    phase: str
    wall: float
    cpu: float
    threads: int
    children: int
    load: float


class PhaseTrace:
    """A worker's trace of its phases: a bounded list in memory, and lines appended to the file
    at `path` (none writes nothing) for a slow phase, a trip and the first errors after it. Every
    reading it makes comes in through the constructor, so a test fakes the clock, the load and
    the pressure folder; a file that cannot be written drops the line."""

    def __init__(
        self,
        path: Path | None,
        *,
        clock: Callable[[], float] = time.monotonic,
        load: Callable[[], tuple[float, float, float]] = os.getloadavg,
        pressure_dir: Path = Path("/proc/pressure"),
    ) -> None:
        self._path = path
        self._clock = clock
        self._load = load
        self._pressure_dir = pressure_dir
        self._entries: deque[PhaseEntry] = deque(maxlen=TRACE_KEPT)
        self._errors_left = 0

    @property
    def entries(self) -> list[PhaseEntry]:
        """The last `TRACE_KEPT` entries, oldest first."""
        return list(self._entries)

    def _write(self, line: Mapping[str, object]) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, default=str) + "\n")
        except OSError:
            pass

    def phase_ended(
        self, nodeid: str, phase: str, *, started: float, start: CpuSnapshot, now: CpuSnapshot
    ) -> None:
        """Add the entry of a phase that began at clock reading `started`; a phase over
        `SLOW_PHASE_SECONDS` of wall time is also written as a `slow` line."""
        entry = PhaseEntry(
            test=nodeid,
            phase=phase,
            wall=self._clock() - started,
            cpu=now.process - start.process,
            threads=len(now.tasks) + len(now.descendants),
            children=len(now.children),
            load=self._load()[0],
        )
        self._entries.append(entry)
        if entry.wall > SLOW_PHASE_SECONDS:
            self._write({"kind": "slow", **entry.model_dump()})

    def _pressure(self) -> dict[str, str]:
        readings: dict[str, str] = {}
        for name in ("cpu", "io"):
            try:
                readings[name] = (self._pressure_dir / name).read_text()
            except OSError:
                readings[name] = "unavailable"
        return readings

    def tripped(
        self,
        nodeid: str,
        phase: str,
        *,
        clock: str,
        start: CpuSnapshot,
        now: CpuSnapshot,
        own: Collection[int],
        left_by: Mapping[int, tuple[str, str]],
    ) -> None:
        """Write the `trip` line: the terms of the billed CPU, the threads and children that
        supplied it, the load, the pressure readings and the last `TRIP_ENTRIES` entries; and
        start counting the errors whose traceback is kept."""
        self._errors_left = TRACED_ERRORS
        terms = phase_cpu_terms(start, now, own)
        threads = [
            {
                "name": left_by_of(left_by, "task", t)[0],
                "left_by": left_by_of(left_by, "task", t)[1],
                "seconds": v - start.tasks.get(t, 0.0),
            }
            for t, v in now.tasks.items()
            if t not in own and v - start.tasks.get(t, 0.0) > 0
        ]
        children = [
            {"pid": p, "seconds": v}
            for p, v in now.descendants.items()
            if p not in start.descendants
        ]
        self._write(
            {
                "kind": "trip",
                "test": nodeid,
                "phase": phase,
                "clock": clock,
                "terms": {**terms.model_dump(), "total": terms.total},
                "threads": threads,
                "children": children,
                "load": list(self._load()),
                "pressure": self._pressure(),
                "recent": [e.model_dump() for e in list(self._entries)[-TRIP_ENTRIES:]],
            }
        )

    def error_raised(self, nodeid: str, phase: str, error: BaseException) -> None:
        """After a trip, write a `traceback` line for each of the next `TRACED_ERRORS` errors."""
        if self._errors_left <= 0:
            return
        self._errors_left -= 1
        self._write(
            {
                "kind": "traceback",
                "test": nodeid,
                "phase": phase,
                "traceback": "".join(traceback.format_exception(error)),
            }
        )


class TimedOut(BaseException):
    """Raised in the main thread when the running test passes its limit; carries the stack
    of every thread as it was then and the children the test was waiting for."""

    def __init__(self, stacks: str = "", children: str = "") -> None:
        super().__init__(stacks)
        self.stacks = stacks
        self.children = children


def thread_stacks() -> str:
    """The stack of every thread now. It runs in a signal handler, which may have interrupted
    code holding a lock of `threading`, so it takes none: `faulthandler` reads the frames
    itself. A host that cannot make the file (no temp folder, no descriptors) says so and the
    limit is still the failure."""
    try:
        with tempfile.TemporaryFile("w+") as dump:
            faulthandler.dump_traceback(dump, all_threads=True)
            dump.seek(0)
            return dump.read()
    except OSError as error:
        return f"(the stacks could not be read: {error})"


# The flag under the kind's old spelling, still accepted with a notice.
OLD_FLAG = "--" + old_spelling(TestTier.E2E_TEST) + "-test-time-limit"
NEW_FLAG = "--e2e-test-time-limit"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini(
        "time_limit_backstop_factor",
        default=str(BACKSTOP_FACTOR),
        help="the wall-clock backstop is this many times the CPU budget",
    )
    parser.addoption("--test-time-limit", type=float, default=DEFAULT_TEST_TIME_LIMIT)
    parser.addoption(NEW_FLAG, type=float, default=None)
    parser.addoption(OLD_FLAG, type=float, default=None)


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption(OLD_FLAG) is None:
        return
    if config.getoption(NEW_FLAG) is not None:
        raise pytest.UsageError(
            f"{OLD_FLAG} and {NEW_FLAG} are both set; {OLD_FLAG} is the old name"
        )
    print(f"warning: {OLD_FLAG} is deprecated; use {NEW_FLAG}", file=sys.stderr)


def e2e_limit(config: pytest.Config) -> float:
    """The limit of an e2e test: the new flag, else the old one, else the default."""
    for flag in (NEW_FLAG, OLD_FLAG):
        if (value := config.getoption(flag)) is not None:
            return value
    return DEFAULT_E2E_TEST_TIME_LIMIT


def limit_for(item: pytest.Item) -> float:
    """The seconds a test's setup, call or teardown may run: marker, e2e or default."""
    if item.get_closest_marker("e2e") is not None:
        return e2e_limit(item.config)
    own = item.get_closest_marker("time_limit")
    if own is None:
        return item.config.getoption("--test-time-limit")
    value = own.kwargs.get("seconds", own.args[0] if own.args else None)
    if value is None:
        pytest.fail("the time_limit marker needs a number of seconds", pytrace=False)
    return float(value)


def _trip_in_chain(error: BaseException) -> TimedOut | None:
    """The `TimedOut` on an exception's `__cause__`/`__context__` chain, if the code under
    test replaced it while unwinding (as `asyncio.run`'s teardown does)."""
    seen: set[int] = set()
    pending: BaseException | None = error
    while pending is not None and id(pending) not in seen:
        if isinstance(pending, TimedOut):
            return pending
        seen.add(id(pending))
        pending = pending.__cause__ or pending.__context__
    return None


_TRACE: list[PhaseTrace] = []


def worker_trace() -> PhaseTrace:
    """This worker's trace, made on first use; it writes to the file `TEST_TRACE_VARIABLE` names and
    nowhere when the variable is not set."""
    if not _TRACE:
        named = os.environ.get(TEST_TRACE_VARIABLE)
        _TRACE.append(PhaseTrace(Path(named) if named else None))
    return _TRACE[0]


def _under_limit(item: pytest.Item, phase: str):
    """Run the rest of a hook, setup, call or teardown, under its budgets."""
    budget = budget_for(item)
    kind = "e2e-test " if item.get_closest_marker("e2e") is not None else ""
    off = budget.cpu <= 0 and budget.wall <= 0
    if off or threading.current_thread() is not threading.main_thread():
        return (yield)
    running = True
    fired: list[str] = []
    main = threading.get_ident()

    def interrupt(signum, frame) -> None:
        if running:
            raise TimedOut(thread_stacks(), running_children())

    first = threading.Lock()

    def stop(clock: str) -> None:
        # Only the first clock signals: a second signal would land in the failure being built.
        with first:
            if fired:
                return
            fired.append(clock)
        signal.pthread_kill(main, signal.SIGUSR2)

    previous = signal.signal(signal.SIGUSR2, interrupt)
    done = threading.Event()
    start = snapshot_cpu() if budget.cpu > 0 else None
    last = [start]  # the watcher's latest reading, for the failure text
    wall_start = time.monotonic()

    timer = threading.Timer(budget.wall, stop, ("wall",)) if budget.wall > 0 else None
    watching: list[int] = []  # the plugin's own threads, which no phase is billed for

    def watch_cpu() -> None:
        watching.append(threading.get_native_id())
        while not done.wait(POLL_SECONDS):
            assert start is not None
            last[0] = snapshot_cpu()
            own = [*watching, *([timer.native_id] if timer and timer.native_id else [])]
            used = phase_cpu(start, last[0], own)
            if clock_fired(budget, used, time.monotonic() - wall_start) == "cpu":
                stop("cpu")
                return

    watcher = threading.Thread(target=watch_cpu, daemon=True) if budget.cpu > 0 else None
    try:
        if timer is not None:
            timer.daemon = True
            timer.start()
        if watcher is not None:
            watcher.start()
        return (yield)
    except BaseException as caught:
        running = False
        stopped = caught if isinstance(caught, TimedOut) else _trip_in_chain(caught)
        if stopped is None or not fired:
            if phase == "setup" and isinstance(caught, Exception):
                worker_trace().error_raised(item.nodeid, phase, caught)
            raise
        if start is not None:
            worker_trace().tripped(
                item.nodeid,
                phase,
                clock=fired[0],
                start=start,
                now=last[0] or start,
                own=[*watching, *([timer.native_id] if timer and timer.native_id else [])],
                left_by=LEFT_BY,
            )
        replaced = (
            ""
            if stopped is caught
            else f"\n\nThe trip was replaced by {type(caught).__name__}: {caught}"
        )
        what = "test" if phase == "call" else f"test {phase}"
        if kind:
            sentence = f"exceeded the {kind}time limit of {budget.wall:g} seconds"
        else:
            sentence = exceeded_text(fired[0] if fired else "wall", budget)
        inherited = inherited_lines(start, last[0] or start, LEFT_BY) if start is not None else []
        blamed = "".join(f"\n{line}" for line in inherited)
        # Raised from None: the stacks are in the text, once, after the limit it names.
        waiting = (
            f"\n\nChild processes running at the limit:\n{stopped.children}"
            if stopped.children
            else ""
        )
        raise pytest.fail.Exception(
            f"{what} {sentence}{blamed}{waiting}{replaced}"
            f"\n\nThe stack of every thread:\n{stopped.stacks}",
            pytrace=False,
        ) from None
    finally:
        running = False
        done.set()
        if timer is not None:
            timer.cancel()
            timer.join()
        if watcher is not None:
            watcher.join()
        signal.signal(signal.SIGUSR2, previous)
        if start is not None:
            ended = snapshot_cpu()
            record_left(start, ended, item.nodeid)
            worker_trace().phase_ended(
                item.nodeid, phase, started=wall_start, start=start, now=ended
            )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    return (yield from _under_limit(item, "setup"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    return (yield from _under_limit(item, "call"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item):
    return (yield from _under_limit(item, "teardown"))
