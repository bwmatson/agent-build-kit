"""A pytest plugin that fails a test which runs past a time limit, from a thread.

The limit, on each of a test's setup, call and teardown, is a CPU budget (the CPU time of
the process and its children) of `--test-time-limit` seconds (default
`DEFAULT_TEST_TIME_LIMIT`), with a wall-clock backstop of `BACKSTOP_FACTOR` times it. A
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
import os
import signal
import sys
import tempfile
import threading
import time

import pytest

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.model import Frozen, TestTier

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
    backstop of `BACKSTOP_FACTOR` times it; an e2e test has only its wall limit."""
    limit = max(limit_for(item), 0)
    if item.get_closest_marker("e2e") is not None:
        return Budget(cpu=0, wall=limit)
    return Budget(cpu=limit, wall=limit * BACKSTOP_FACTOR)


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


def _scan_descendants_cpu() -> dict[int, float]:
    """The same reading for a kernel without per-task children files: every process is read."""
    children: dict[int, list[tuple[int, float]]] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            fields = _stat_fields(name)
        except OSError:
            continue
        children.setdefault(int(fields[1]), []).append((int(name), _spent(fields)))
    found: dict[int, float] = {}
    pending = [os.getpid()]
    while pending:
        for pid, spent in children.get(pending.pop(), []):
            found[pid] = spent
            pending.append(pid)
    return found


def descendants_cpu() -> dict[int, float]:
    """Process id to CPU seconds, from /proc, of each running descendant, including what it has
    already collected from its own finished children. Only descendants are read, so a test with
    no children costs one small read. A host without /proc has none."""
    me = os.getpid()
    try:
        if not os.path.exists(f"/proc/{me}/task/{me}/children"):
            return _scan_descendants_cpu()
        pending = _child_pids(me)
        found: dict[int, float] = {}
        while pending:
            pid = pending.pop()
            try:
                found[pid] = _spent(_stat_fields(pid))
            except OSError:
                continue
            pending.extend(_child_pids(pid))
        return found
    except OSError:
        return {}


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
    return CpuSnapshot(process=process, tasks=tasks, descendants=descendants_cpu(), reaped=reaped)


def phase_cpu(start: CpuSnapshot, now: CpuSnapshot) -> float:
    """The CPU a phase used: the process's growth (threads that started and ended in the phase
    included) less the growth of each thread in `start` that is still alive, plus all of each
    descendant not in `start`, plus the growth of what finished children gave. An inherited
    thread that exits during the phase is still billed for its last moments."""
    inherited = sum(v - start.tasks[tid] for tid, v in now.tasks.items() if tid in start.tasks)
    new_descendants = sum(v for pid, v in now.descendants.items() if pid not in start.descendants)
    return (now.process - start.process) - inherited + new_descendants + (now.reaped - start.reaped)


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
            name, test = left_by.get(ident, (f"{kind} {ident}", "an earlier test"))
            lines.append(
                f"{name} ({kind} {ident}), left running by {test}, used {grew:.2f} s of CPU "
                "in this phase"
            )
    return lines


class TimedOut(BaseException):
    """Raised in the main thread when the running test passes its limit; carries the stack
    of every thread as it was then."""

    def __init__(self, stacks: str = "") -> None:
        super().__init__(stacks)
        self.stacks = stacks


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
            raise TimedOut(thread_stacks())

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

    def watch_cpu() -> None:
        while not done.wait(POLL_SECONDS):
            assert start is not None
            last[0] = snapshot_cpu()
            used = phase_cpu(start, last[0])
            if clock_fired(budget, used, time.monotonic() - wall_start) == "cpu":
                stop("cpu")
                return

    timer = threading.Timer(budget.wall, stop, ("wall",)) if budget.wall > 0 else None
    watcher = threading.Thread(target=watch_cpu, daemon=True) if budget.cpu > 0 else None
    try:
        if timer is not None:
            timer.daemon = True
            timer.start()
        if watcher is not None:
            watcher.start()
        return (yield)
    except TimedOut as stopped:
        running = False
        what = "test" if phase == "call" else f"test {phase}"
        if kind:
            sentence = f"exceeded the {kind}time limit of {budget.wall:g} seconds"
        else:
            sentence = exceeded_text(fired[0] if fired else "wall", budget)
        inherited = inherited_lines(start, last[0] or start, LEFT_BY) if start is not None else []
        blamed = "".join(f"\n{line}" for line in inherited)
        # Raised from None: the stacks are in the text, once, after the limit it names.
        raise pytest.fail.Exception(
            f"{what} {sentence}{blamed}\n\nThe stack of every thread:\n{stopped.stacks}",
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
            record_left(start, snapshot_cpu(), item.nodeid)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    return (yield from _under_limit(item, "setup"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item):
    return (yield from _under_limit(item, "call"))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item):
    return (yield from _under_limit(item, "teardown"))
