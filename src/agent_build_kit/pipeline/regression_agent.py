"""The regression agent: works out why a test fails and since when, judges whether the test or
the implementation is wrong, and writes the one change that fixes it (spec: regression-agent).
"""

from __future__ import annotations

import contextlib
import re
from enum import StrEnum
from pathlib import Path

from agent_build_kit import openspec
from agent_build_kit.config import CONFIG_FILENAME, active, models
from agent_build_kit.init.propose import repair_once, validation_report
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.flakes import (
    Flake,
    failure_history,
    next_fix_name,
    open_fix_change,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.pipeline.work_graph import (
    PRIORITY_LINE,
    declared_projects,
    declared_split_names,
)
from agent_build_kit.runtimes import AgentRequest, AgentRuntime
from agent_build_kit.runtimes.base import ToolPolicy
from agent_build_kit.sandboxes import Coverage, SandboxPolicy

# What the agent ends its answer with when it cannot tell whether the test or the implementation
# is wrong.
UNDECIDED = "JUDGEMENT: undecided"
# The files a complete change holds besides its delta specs.
CHANGE_FILES = ("proposal.md", "design.md", "tasks.md")
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
{base_section}{history}"""


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
        name = open_fix_change(inst, failure.test)[0] or next_fix_name(inst, failure.test)
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
    )
    stopped: FixOutcome | None = None

    def attempt(asked: str) -> list[str]:
        nonlocal stopped
        request = AgentRequest(
            prompt=asked,
            role="regression",
            change=name,
            cwd=cwd,
            # The change is written in the planning repo, beside the checkout the agent works in.
            add_dirs=(inst.specs_dir,),
            model=models().regression or None,
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
                sandbox=SandboxPolicy(
                    write=(root,),
                    read=(cwd, inst.specs_dir),
                    hosts=(),
                    required=Coverage.NONE,
                ),
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
            return _problems(inst, name, run_openspec)
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
    if stopped is not None:
        return stopped
    if problems:
        return FixOutcome(change=name, held=True, reason="; ".join(problems))
    return FixOutcome(change=name)


def _problems(inst: Installation, name: str, run_openspec: openspec.Run | None) -> list[str]:
    """What is wrong with the change `name`: a file missing, what OpenSpec or the tags check
    refuses, no `[contract]` group or no `Priority:` line."""
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
    return found + _exposure_problems((root / "proposal.md").read_text())


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
