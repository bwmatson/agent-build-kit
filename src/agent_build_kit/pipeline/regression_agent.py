"""The regression agent: works out why a test fails and since when, judges whether the test or
the implementation is wrong, and writes the one change that fixes it (spec: regression-agent).
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from agent_build_kit import openspec, runtimes
from agent_build_kit.config import CONFIG_FILENAME, active, models
from agent_build_kit.init.propose import repair_once, validation_report
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.check_runner import worktree_at
from agent_build_kit.pipeline.external_file import HELD, Hold, add_hold, already_held, read_holds
from agent_build_kit.pipeline.file_lock import (
    Clock,
    LockTimeout,
    atomic_write_text,
    file_lock,
    try_file_lock,
)
from agent_build_kit.pipeline.flakes import (
    FAILING_TEST_LABEL,
    FAILING_TEST_LINE,
    Flake,
    add_needs_to_unit,
    fix_change_name,
    flake_record,
    is_fix_change,
    next_fix_name,
    open_fix_change,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import local_ref
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.pipeline.work_graph import (
    FIX_PREFIX,
    PRIORITY_LINE,
    declared_projects,
    declared_split_names,
    group_needs,
)
from agent_build_kit.runtimes import AgentRequest, AgentRuntime
from agent_build_kit.runtimes.base import ToolPolicy
from agent_build_kit.sandboxes import SandboxPolicy
from agent_build_kit.sandboxes.policy import PolicyRefused, git_parts
from agent_build_kit.settings import settings

# What the agent ends its answer with when it cannot tell whether the test or the implementation
# is wrong.
UNDECIDED = "JUDGEMENT: undecided"
# The files a complete change holds besides its delta specs.
CHANGE_FILES = ("proposal.md", "design.md", "tasks.md")
# When each run was started, one timestamp a line, in the state directory.
RUNS_FILE = "regression-runs.jsonl"
# Who holds a change whose run ended for a person to look at (see `abk external`).
HELD_HOLDER = "a person"
# How long a run counts against `global_limits.max_regression_runs_per_hour`.
RUN_WINDOW = timedelta(hours=1)
# What the note of a unit held for the cap starts with.
CAPPED_NOTE = "waiting for a regression-agent run: "
# What the agent may use beside the repo's own commands for running a test: it reads the code and
# the history of the base and writes its change. No command moves the base checkout's HEAD, and
# none reaches the code host. A prefix pattern cannot refuse a flag, so `--output=<path>` and
# `--ext-diff` are not kept out by this list: where a sandbox backend is available, its write
# list is what limits them; without one the hook sees only the Edit and Write calls. That list
# grants the change directory and whatever the runtime and the profile grant (the Claude runtime
# grants the temp folder). The agent reads a disposable worktree of the unit's base (or of the
# default branch when the failure names none) that `worktree_at` makes under the temp folder: it
# is writable wherever the runtime grants that folder, and thrown away with the run. The repo's
# test commands that follow `TOOLS` run there, so they can prepare their environment in it. Only
# when no worktree can be made does it read the repo's own checkout, outside those grants and
# so read-only, where those commands are refused.
TOOLS = "Read Edit Write Grep Glob Bash(git log*) Bash(git show*) Bash(git blame*) Bash(git diff*)"
# The line of the proposal that names the kind of failure the change is for (a `FixKind`).
KIND_LABEL = "Kind:"
KIND_LINE = re.compile(rf"^\W*{re.escape(KIND_LABEL)}\s*(?P<kind>[\w-]+)[\s`.,;:*]*$", re.MULTILINE)
# How long a unit waits between looks for the change of a run that is in flight.
BUSY_RETRY_SECONDS = 1.0
# The line of the proposal that says which side is wrong, and the two things it may say.
JUDGEMENT_LABEL = "Judgement:"
JUDGEMENTS = ("the test is wrong", "the implementation is wrong")
JUDGEMENT_LINE = re.compile(
    rf"^\W*{JUDGEMENT_LABEL}\s*({'|'.join(re.escape(each) for each in JUDGEMENTS)})",
    re.MULTILINE | re.IGNORECASE,
)


def allowed_tools(inst: Installation, repo: str) -> str:
    """The tool list the agent runs under for a unit of `repo`: `TOOLS` and the commands the
    repo allows an agent to run a test with, each as a pattern."""
    from agent_build_kit.config import AGENT_PATH_WORD, AgentPurpose
    from agent_build_kit.pipeline import agent_commands  # imports wiring, which imports this

    patterns: dict[str, None] = {}
    for item in agent_commands.effective(inst.repo(repo)):
        if item.purpose is not AgentPurpose.TEST:
            continue
        # A command that takes a path allows any path: the pattern ends where the path stood.
        head = (
            item.command[: item.command.index(AGENT_PATH_WORD)]
            if AGENT_PATH_WORD in item.command
            else item.command
        )
        wild = " *" if len(head) < len(item.command) else "*"
        patterns[f"Bash({' '.join(head)}{wild})"] = None
    return f"{TOOLS} {' '.join(patterns)}".strip()


# The proposal's section naming the tests that share the cause, and the line of a cause that is not
# a pattern (spec: regression-same-exposure).
EXPOSURE_HEADING = "## Same exposure"
NONE_FORM = "Same exposure: none, the cause is specific to this test"
POSSIBLE_LINE = (
    "Possible, in scope if you show they share the cause: <test ids>. "
    "Say which in the commit body and what showed it."
)
_EXPOSURE_LINE = re.compile(r"^- \S.*? — \S.* — (confirmed|possible)$")

PROMPT = """\
You are the regression agent. The test `{test}` fails and the unit that met it did not write it.
Work out why it fails and since when, judge whether the test or the implementation is wrong,
and write the one change that fixes it, in the directory `{directory}`: proposal.md (Why, with
the cause, the commit it began at, the base and your judgement; What Changes; Impact),
design.md, tasks.md and a delta spec under specs/<capability>/spec.md.

State the judgement in proposal.md on a line of its own, worded exactly {judgements}. Name the
failing test on a line of its own too, exactly `{failing_label} {test}`: the kit reads it to
reproduce the failure when the change is built. And the kind of failure on a line of its own,
exactly `{kind_label} {kind}`.

The change is named `{change}`. Its tasks.md carries a `Priority:` line and a task group
flagged `[contract]`. If you cannot decide which side is wrong, end your answer with the line
`{undecided}` and write the change anyway.

Same exposure. Once you have judged the cause, say whether it is a pattern: a helper or fixture
many tests call that repeats work or is slow, a test that reads or walks a directory the run or
another test can change, a fixed time budget on a call whose cost depends on the machine, or
shared mutable state. If it is, name the pattern in one line, then search the test tree for other
tests with the same shape, with read-only tools only (grep, reading files). Do not run the tests
you find. Mark each one `confirmed` (the shared code or the same call is visible) or `possible`
(you cannot show it). There is no limit on how many you list; list every one.

Write them in proposal.md under a `## Same exposure` heading, one line per test:
`- <test id> — <the line that shows the shared cause> — confirmed` (or `possible`). If the cause
is not a pattern, write the line `{none_form}` under that heading instead.

In tasks.md, name the shared cause (or the shared helper, which covers all its users) and put only
the `confirmed` tests in the steps. Add one standing line to the task group naming the `possible`
tests, exactly: `{possible_line}`

Kind of failure: {kind}
Checkout (the unit's base, {base}): {cwd}
Command: {command}
Unit: {unit}

Evidence from the run:
{evidence}

Output of the failing run:
{output}
{base_section}{history}{again}"""


class FixKind(StrEnum):
    """What kind of failure the change is written for."""

    FLAKY = "flaky"
    PRE_EXISTING = "pre-existing"
    REGRESSION = "regression"


class FixOutcome(Frozen):
    """The change the agent wrote, and whether a person has to look at it before the unit's wait
    on it can end: `held` with the reason it could not be accepted."""

    change: str
    held: bool = False
    reason: str = ""


def run_regression_agent(
    inst: Installation,
    failure: Flake,
    unit: StoredUnit,
    *,
    kind: FixKind,
    base: str,
    base_output: str = "",
    runtime: AgentRuntime,
    cwd: Path,
    run_openspec: openspec.Run | None = None,
) -> FixOutcome:
    """Run the agent for `failure` in `cwd`, a checkout of the unit's `base`, and check the
    change it wrote with what `abk check` and `abk tags` run, then its own checks: the files, a
    `[contract]` group and a `Priority:` line. A change that fails is rewritten once, then held.
    A run that fails, or that cannot decide, is held at once, with no second run.

    The change's name is taken, and its directory made, under the flakes lock. An open fix of the
    test that holds a `tasks.md` is the change, whether it is in flight or held for a person, and
    is answered without a run: two units that meet one test get one change, written once. A
    directory without one was left by a run that failed, and is written again. The lock is not
    held for the run, so the caller serialises the runs for one test. An exception of the runtime
    (a rate limit, an interruption) propagates to the caller, after the directory made for the
    run is removed if nothing was written in it."""
    with file_lock(inst.state_dir / "flakes.lock"):
        open_change, archived = open_fix_change(inst, failure.test)
        name = open_change or next_fix_name(inst, failure.test)
        root = inst.changes_dir / name
        if (root / "tasks.md").is_file():
            return FixOutcome(change=name)
        root.mkdir(parents=True, exist_ok=True)
    on_base = (
        f"\nOutput of the same test on the base:\n{base_output.strip()}\n"
        if kind is not FixKind.FLAKY and base_output
        else ""
    )
    earlier = failure_history(inst, failure.test, evidence=True)
    prompt = PROMPT.format(
        test=failure.test,
        directory=root,
        change=name,
        undecided=UNDECIDED,
        none_form=NONE_FORM,
        possible_line=POSSIBLE_LINE,
        kind=kind.value,
        base=base,
        cwd=cwd,
        command=failure.command,
        unit=failure.unit or unit.id,
        evidence=failure.evidence or "none recorded",
        output=failure.output.strip(),
        base_section=on_base,
        history="\nEarlier failures of this test:\n" + "\n".join(earlier) if earlier else "",
        failing_label=FAILING_TEST_LABEL,
        kind_label=KIND_LABEL,
        judgements=" or ".join(f"`{JUDGEMENT_LABEL} {each}`" for each in JUDGEMENTS),
        again=(
            f"\nAn earlier change, `{archived}`, fixed this test and was merged and archived; "
            "it fails again. Read it, and say why its fix did not hold. Its requirement is in the "
            "shipped spec now, and an archive refuses an ADDED requirement of a title the "
            "shipped spec holds: restate it as a MODIFIED one.\n"
            if archived
            else ""
        ),
    )
    stopped: FixOutcome | None = None

    def attempt(asked: str) -> list[str]:
        nonlocal stopped
        try:
            confined = agent_sandbox(inst, unit.repo, cwd, root, runtime)
        except PolicyRefused as refused:
            stopped = FixOutcome(
                change=name, held=True, reason=f"the sandbox policy was refused: {refused}"
            )
            return []
        request = AgentRequest(
            prompt=asked,
            role="regression",
            change=name,
            cwd=cwd,
            # The change is written in the planning repo, beside the checkout the agent works in.
            add_dirs=(inst.specs_dir,),
            model=models().regression or None,
            allowed_tools=allowed_tools(inst, unit.repo),
            permission_mode="edit",
            planning_repo=inst.root,
            planning_change_dir=root,
            policy=ToolPolicy(
                # The base checkout is read-only to the hook, whether or not a sandbox confines
                # the run: editing it would corrupt the next comparison with the base.
                specs_dir=cwd,
                branch_prefix=active().git.branch_prefix,
                # The checkout is the unit's base: nothing is committed there.
                no_commit=True,
                fenced_files=(inst.root / CONFIG_FILENAME,),
                sandbox=confined,
            ),
        )
        result = runtime.run(
            recorded(
                request,
                runtime,
                node=OverheadNode.REGRESSION,
                unit=unit.id,
                change=name,
                say=print,
            )
        )
        if not result.succeeded:
            reason = result.error or result.stop_reason or "no reason given"
            stopped = FixOutcome(change=name, held=True, reason=f"the agent's run failed: {reason}")
        elif UNDECIDED in result.text:
            stopped = FixOutcome(
                change=name, held=True, reason="the agent could not decide which side is wrong"
            )
        else:
            return _problems(inst, name, failure.test, kind, run_openspec)
        return []

    try:
        problems = repair_once(
            attempt,
            prompt,
            lambda found: (
                "\nThe change you wrote was refused. Rewrite it to fix:\n"
                + "\n".join(f"- {problem}" for problem in found)
                + "\n"
            ),
        )
    except BaseException:
        with contextlib.suppress(OSError):
            root.rmdir()  # only an empty directory goes
        raise
    held = stopped or (
        FixOutcome(change=name, held=True, reason="; ".join(problems)) if problems else None
    )
    if held is None:
        return FixOutcome(change=name)
    # A person looks at it before the kit builds it: the whole change is held, as work handed to
    # someone outside the kit is (`abk external release <change> --all` gives it back, and works
    # for a change with no groups). No unit of it starts (the planner may still plan it), `abk
    # status` says why, `abk explain` too for a unit of that change, and a directory with no
    # tasks.md is not taken for one a dead run left.
    hold = Hold(
        scope="all",
        holder=HELD_HOLDER,
        link=held.reason,
        since=spans.clock.now(),
        note=held.reason,
    )
    if not already_held(root, hold):
        add_hold(root, hold)
    return held


def agent_sandbox(
    inst: Installation, repo: str, cwd: Path, root: Path, runtime: AgentRuntime
) -> SandboxPolicy | None:
    """The sandbox the agent runs under, from the same parts as a build step's (the system
    folders, the runtime's and the profile's paths and hosts, the files that load the
    installation, git's reads) and the same gates (none while `sandbox.enabled` is false or where
    no backend exists), but the checkout and its git directory are not granted for writing, as
    they are to a build, and the change directory `root` is the only path of the planning repo
    it writes. What the runtime or the profile grants (the Claude runtime grants the temp folder)
    still covers a checkout inside it, such as the disposable worktree of the run."""
    from agent_build_kit.pipeline import wiring  # imports this module

    built = wiring.sandbox_policy(repo, cwd, runtime, None, changes=(root.name,))
    if built is None:
        return None
    left_out = {cwd.resolve(), *git_parts(cwd)}
    return built.model_copy(
        update={
            "write": (*(path for path in built.write if path not in left_out), root.resolve()),
            "read": (*built.read, cwd.resolve(), inst.specs_dir.resolve()),
        }
    )


def held_for_a_person(change_dir: Path) -> bool:
    """Whether the run for the change in `change_dir` ended held for a person and no one has
    given it back."""
    return any(h.status == HELD and h.holder == HELD_HOLDER for h in read_holds(change_dir))


def failure_history(inst: Installation, test: str, *, evidence: bool = False) -> list[str]:
    """One line for each recorded failure of `test`, in the flake record and in the pre-existing
    one, oldest first, with the evidence of its run when `evidence` is set."""
    rows = [*flake_record(inst).entries(), *preexisting_record(inst).entries()]
    return [
        f"- {e.at:%Y-%m-%d %H:%M} UTC, unit {e.unit}" + (f": {e.evidence}" if evidence else "")
        for e in sorted((row for row in rows if row.test == test), key=lambda row: row.at)
    ]


def _problems(
    inst: Installation, name: str, test: str, kind: FixKind, run_openspec: openspec.Run | None
) -> list[str]:
    """What is wrong with the change `name` for `test`: a file missing, what OpenSpec or the
    tags check refuses, no `[contract]` group, no `Priority:` line, no judgement line, no
    `Failing test:` line naming `test` or no `Kind:` line naming `kind` in the proposal."""
    root = inst.changes_dir / name
    missing = [file for file in CHANGE_FILES if not (root / file).is_file()]
    if not any((root / "specs").glob("*/spec.md")):
        missing.append("a delta spec under specs/<capability>/spec.md")
    if missing:
        return [f"missing {', '.join(missing)}"]
    repos = tuple(inst.repos)
    projects = declared_projects(inst.repos)
    splits = declared_split_names(inst.repos, inst.config)
    groups, found = validation_report(
        inst.root,
        name,
        repos=repos,
        projects=projects,
        splits=splits,
        run_openspec=run_openspec,
        specs_dir=inst.config.planning.specs_dir,
    )
    tasks = root / "tasks.md"
    if not any(group.flag == "contract" for group in groups):
        found.append("tasks.md: no task group is flagged [contract]")
    if not any(PRIORITY_LINE.match(line.strip()) for line in tasks.read_text().splitlines()):
        found.append("tasks.md: no `Priority:` line")
    named = FAILING_TEST_LINE.search((root / "proposal.md").read_text())
    if not named or named["test"] != test:
        found.append(f"proposal.md: no line `{FAILING_TEST_LABEL} {test}` naming the failing test")
    told = KIND_LINE.search((root / "proposal.md").read_text())
    if not told or told["kind"] != kind.value:
        found.append(f"proposal.md: no line `{KIND_LABEL} {kind.value}` naming the kind of failure")
    if not JUDGEMENT_LINE.search((root / "proposal.md").read_text()):
        found.append(
            "proposal.md: no judgement line, worded "
            + " or ".join(f"`{JUDGEMENT_LABEL} {each}`" for each in JUDGEMENTS)
        )
    return found + _exposure_problems((root / "proposal.md").read_text())


class RegressionRunCapped(Exception):
    """The hour's runs of the agent are all started: no run for this test now. The unit is held,
    not failed, and the run starts on a later tick once the hour has room."""

    def __init__(self, test: str, cap: int) -> None:
        self.note = (
            f"{CAPPED_NOTE}{cap} runs an hour have started "
            f"(global_limits.max_regression_runs_per_hour), none for {test}"
        )
        super().__init__(self.note)


class Met(Frozen):
    """What the failures of one run came to when each was told to the handler: the change each
    one waits on (None for a unit of that change itself, and for one the cap held back), which
    ones the cap held back, and the note of the first."""

    answers: list[str | None]
    held_back: list[bool]
    note: str = ""

    @property
    def capped(self) -> bool:
        """Whether the hour's cap held back any failure."""
        return any(self.held_back)

    @property
    def all_answered(self) -> bool:
        """Whether every failure the cap did not hold back has a change to lean on. A failure the
        cap held back is recorded without one and does not count against the unit; one with no
        change otherwise (the unit is of the change itself) does."""
        return all(
            answer for answer, held in zip(self.answers, self.held_back, strict=True) if not held
        )


def meet_all(calls: Iterable[Callable[[], str | None]]) -> Met:
    """Make every call, each of which may raise `RegressionRunCapped`. A failure the hour's cap
    holds back does not stop the ones after it from being recorded and waited on."""
    answers: list[str | None] = []
    held_back: list[bool] = []
    note = ""
    for call in calls:
        try:
            answers.append(call())
            held_back.append(False)
        except RegressionRunCapped as stopped:
            answers.append(None)
            held_back.append(True)
            note = note or stopped.note
    return Met(answers=answers, held_back=held_back, note=note)


def _run_times(inst: Installation) -> list[datetime]:
    try:
        lines = (inst.state_dir / RUNS_FILE).read_text().splitlines()
    except OSError:
        return []
    return [datetime.fromisoformat(line) for line in lines if line.strip()]


def runs_in_the_last_hour(inst: Installation, now: datetime) -> int:
    """How many regression-agent runs were started in the hour before `now`."""
    return sum(1 for at in _run_times(inst) if now - at < RUN_WINDOW)


def run_room(inst: Installation, now: datetime | None = None) -> bool:
    """Whether another run may start now."""
    cap = active().global_limits.max_regression_runs_per_hour
    return runs_in_the_last_hour(inst, now or spans.clock.now()) < cap


def _take_run(inst: Installation, test: str, now: datetime) -> None:
    """Count a run started now against the hour, forgetting the runs older than it, or raise
    `RegressionRunCapped`."""
    with file_lock(inst.state_dir / "regression-agent.lock"):
        if not run_room(inst, now):
            raise RegressionRunCapped(test, active().global_limits.max_regression_runs_per_hour)
        kept = [at for at in _run_times(inst) if now - at < RUN_WINDOW]
        text = "".join(f"{at.isoformat()}\n" for at in [*kept, now])
        atomic_write_text(inst.state_dir / RUNS_FILE, text)  # readers take no lock


def wait_on_regression(
    inst: Installation,
    failure: Flake,
    unit: StoredUnit,
    *,
    kind: FixKind,
    runtime: AgentRuntime | None,
    base_output: str = "",
    run_openspec: openspec.Run | None = None,
    wait: bool = True,
    now: datetime | None = None,
    say: Callable[[str], None] = print,
    clock: Clock = time,
) -> str | None:
    """Make sure one open change fixes `failure.test` and, with `wait`, give each group of `unit`
    a `Needs:` line on it, and name it on the earlier records of the test. An open change is
    waited on without a run, also while another unit's run of the agent for it is in flight (the
    lock of the test is then busy and is not waited on: the unit retries after a `clock` pause
    until the run's folder appears, for up to `lock_wait_seconds`, then raises `LockTimeout`).
    With none, the agent runs in a disposable worktree of `failure.base` (the unit's own base:
    its parent's branch tip when stacked) or, when the failure names none, of the default
    branch; only a worktree that cannot be made leaves it in the repo's own checkout.
    `RegressionRunCapped` is raised when
    `global_limits.max_regression_runs_per_hour` runs have started in the last hour. Answers None
    for a unit of the change itself, which waits on nothing. The runs for one test are
    serialised, and the runs of different tests are not."""
    test_lock = inst.state_dir / f"regression-{fix_change_name(failure.test, FIX_PREFIX)}.lock"

    def settled() -> str:
        """The change for the test, written by a run of the agent when there is none; the caller
        holds the lock of the test."""
        name = open_fix_change(inst, failure.test)[0]
        # A directory without a tasks.md was left by a run that died and is written again, unless
        # the run ended held for a person, which is waited on as it is.
        if name is not None and (
            (inst.changes_dir / name / "tasks.md").is_file()
            or held_for_a_person(inst.changes_dir / name)
        ):
            return name
        _take_run(inst, failure.test, now or spans.clock.now())
        checkout = inst.checkouts[unit.repo]
        ref = failure.base or local_ref(inst.repo(unit.repo).default_branch, repo=unit.repo)
        with contextlib.ExitStack() as stack:
            cwd, base = checkout, inst.repo(unit.repo).default_branch
            try:
                cwd = stack.enter_context(worktree_at(checkout, ref))
                base = ref
            except (subprocess.CalledProcessError, OSError) as error:
                say(f"no worktree of {ref}, using the checkout instead: {error}")
            outcome = run_regression_agent(
                inst,
                failure,
                unit,
                kind=kind,
                base=base,
                base_output=base_output,
                runtime=runtime or runtimes.active(),
                cwd=cwd,
                run_openspec=run_openspec,
            )
        if outcome.held:
            say(f"{outcome.change}: held for a person — {outcome.reason}")
        flake_record(inst).link(failure.test, outcome.change)
        preexisting_record(inst).link(failure.test, outcome.change)
        return outcome.change

    # A run of the agent can take minutes and the lock of the test is held for all of it, so it is
    # never waited on. A unit that meets the test meanwhile takes the open change and waits on it;
    # when the run has not made its folder yet (it makes a worktree first), the unit looks again
    # after a pause, until it takes the lock itself or the folder appears.
    began = clock.monotonic()
    while True:
        with try_file_lock(test_lock) as taken:
            name = settled() if taken else open_fix_change(inst, failure.test)[0]
        if name is not None:
            break
        if clock.monotonic() - began >= settings.lock_wait_seconds:
            raise LockTimeout(f"the run for {failure.test} made no change in time")
        clock.sleep(BUSY_RETRY_SECONDS)
    if unit.change == name:
        return None
    if wait and not is_fix_change(unit.change):  # a unit of a fix change waits on no other fix
        reason = {
            FixKind.FLAKY: f"flaky test {failure.test}",
            FixKind.PRE_EXISTING: f"failing test {failure.test} on the base",
            FixKind.REGRESSION: f"failing test {failure.test}",
        }[kind]
        add_needs_to_unit(inst, unit, name, reason)
    return name


def judgement_of(inst: Installation, change: str) -> str:
    """What the agent judged in `change`, from the `Judgement:` line of its proposal ("the test
    is wrong", "the implementation is wrong"); empty when it has none."""
    try:
        text = (inst.changes_dir / change / "proposal.md").read_text()
    except OSError:
        return ""
    found = JUDGEMENT_LINE.search(text)
    return found[1].lower() if found else ""


def waited_fixes(inst: Installation, unit: StoredUnit) -> list[tuple[str, str]]:
    """Each change `unit` waits on through a `Needs:` line, with the agent's judgement of it (empty
    for a change it did not write)."""
    changes: dict[str, str] = {}
    for member in unit.members():
        tasks = inst.changes_dir / member.change / "tasks.md"
        if not tasks.is_file():
            continue
        needs = group_needs(tasks)
        for group in member.groups:
            for need in needs.get(group, []):
                changes.setdefault(need.change, judgement_of(inst, need.change))
    return list(changes.items())


def _exposure_problems(proposal: str) -> list[str]:
    """What is wrong with the proposal's `Same exposure` section: it is missing or empty, or a
    line is neither the `none` form nor `- <test id> — <evidence> — confirmed|possible`. The
    content of the lines is not judged."""
    lines = proposal.splitlines()
    starts = [n for n, line in enumerate(lines) if line.strip() == EXPOSURE_HEADING]
    if not starts:
        return [
            f"proposal.md: no `{EXPOSURE_HEADING}` section (see the Same exposure instructions)"
        ]
    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## "):
            break
        if line.strip():
            body.append(line.strip())
    if not body:
        return ["proposal.md: the Same exposure section is empty"]
    return [
        f"proposal.md: Same exposure line is neither `{NONE_FORM}` nor "
        f"`- <test id> — <evidence> — confirmed|possible`: {line}"
        for line in body
        if not (line.startswith(NONE_FORM) or _EXPOSURE_LINE.match(line))
    ]
