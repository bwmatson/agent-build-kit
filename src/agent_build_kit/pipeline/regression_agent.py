"""The regression agent: works out why a test fails and since when, judges whether the test or
the implementation is wrong, and writes the one change that fixes it (spec: regression-agent).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from agent_build_kit.config import models
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.flakes import Flake, flake_record, next_fix_name
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.pipeline.work_graph import PRIORITY_LINE, validate_tasks
from agent_build_kit.runtimes import AgentRequest, AgentRuntime
from agent_build_kit.runtimes.base import ToolPolicy
from agent_build_kit.sandboxes import Coverage, SandboxPolicy

# What the agent ends its answer with when it cannot tell whether the test or the implementation
# is wrong.
UNDECIDED = "JUDGEMENT: undecided"
# The files a complete change holds besides its delta specs.
CHANGE_FILES = ("proposal.md", "design.md", "tasks.md")

PROMPT = """\
You are the regression agent. The test `{test}` fails and the unit that met it did not write it.
Work out why it fails and since when, judge whether the test or the implementation is wrong,
and write the one change that fixes it, in the directory `{directory}`: proposal.md (Why, with
the cause, the commit it began at, the base and your judgement; What Changes; Impact),
design.md, tasks.md and a delta spec under specs/<capability>/spec.md.

The change is named `{change}`. Its tasks.md carries a `Priority:` line and a task group
flagged `[contract]`. If you cannot decide which side is wrong, end your answer with the line
`{undecided}` and write the change anyway.

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


def write_fix_change(
    inst: Installation,
    failure: Flake,
    unit: StoredUnit,
    *,
    kind: FixKind,
    base: str,
    base_output: str = "",
    runtime: AgentRuntime,
    cwd: Path,
) -> FixOutcome:
    """Run the agent for `failure` in `cwd`, a checkout of the unit's `base`, and check the
    change it wrote."""
    name = next_fix_name(inst, failure.test)
    root = inst.changes_dir / name
    on_base = (
        f"\nOutput of the same test on the base:\n{base_output.strip()}\n"
        if kind is not FixKind.FLAKY and base_output
        else ""
    )
    prompt = PROMPT.format(
        test=failure.test,
        directory=root,
        change=name,
        undecided=UNDECIDED,
        kind=kind.value,
        base=base,
        cwd=cwd,
        command=failure.command,
        unit=failure.unit or unit.id,
        evidence=failure.evidence or "none recorded",
        output=failure.output.strip(),
        base_section=on_base,
        history=_history(inst, failure.test),
    )
    problems: list[str] = []
    for _ in range(2):
        asked = prompt
        if problems:
            listed = "\n".join(f"- {problem}" for problem in problems)
            asked += f"\nThe change you wrote was refused. Rewrite it to fix:\n{listed}\n"
        request = AgentRequest(
            prompt=asked,
            role="regression",
            change=name,
            cwd=cwd,
            model=models().regression or None,
            policy=ToolPolicy(
                sandbox=SandboxPolicy(
                    write=(root,),
                    read=(cwd, inst.specs_dir),
                    hosts=(),
                    required=Coverage.NONE,
                )
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
        if UNDECIDED in result.text:
            return FixOutcome(
                change=name, held=True, reason="the agent could not decide which side is wrong"
            )
        problems = _problems(root)
        if not problems:
            return FixOutcome(change=name)
    return FixOutcome(change=name, held=True, reason="; ".join(problems))


def _history(inst: Installation, test: str) -> str:
    seen = [entry for entry in flake_record(inst).entries() if entry.test == test]
    if not seen:
        return ""
    return "\nEarlier failures of this test:\n" + "\n".join(
        f"- {entry.at:%Y-%m-%d %H:%M} UTC, unit {entry.unit}: {entry.evidence}" for entry in seen
    )


def _problems(root: Path) -> list[str]:
    """What is wrong with the change at `root`: a file missing, a task group the tags check
    refuses, no `[contract]` group or no `Priority:` line."""
    missing = [name for name in CHANGE_FILES if not (root / name).is_file()]
    if not any((root / "specs").glob("*/spec.md")):
        missing.append("a delta spec under specs/<capability>/spec.md")
    if missing:
        return [f"missing {', '.join(missing)}"]
    tasks = root / "tasks.md"
    groups, errors = validate_tasks(tasks)
    # The fix is flagged [contract] for its priority in the graph; it widens nothing, so the
    # rule that a widening ends with a [narrow] group does not apply to it.
    found = [f"tasks.md:{error}" for error in errors if "[narrow]" not in error.message]
    if not any(group.flag == "contract" for group in groups):
        found.append("tasks.md: no task group is flagged [contract]")
    if not any(PRIORITY_LINE.match(line.strip()) for line in tasks.read_text().splitlines()):
        found.append("tasks.md: no `Priority:` line")
    return found
