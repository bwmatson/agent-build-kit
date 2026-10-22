"""Running the checks of the manual steps units wait on, each tick pass (spec: manual-steps).

A check is a command run in the unit's worktree under a timeout, with no agent and no usage
reading. An exit status of 0 marks the step done, for good; anything else, an error or a timeout
leaves it unmet and records why. The result is kept on the step, and a changed one is also a
history entry of the unit.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from agent_build_kit.budget import cut_head
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import KEEP, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED, ManualStep
from agent_build_kit.pipeline.workspaces import worktree_path
from agent_build_kit.redaction import redact_text

# Where a builder writes the check script of a step it raises, in its worktree.
MANUAL_FOLDER = ".abk/manual"
# The longest line of a check's output that is kept.
LINE_LIMIT = 300
# All a check is given of the environment: it reads the repository, not the machine's secrets.
_ENVIRONMENT = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}

Outcome = Literal["met", "unmet", "failed", "timeout"]


class ManualAction(Frozen):
    """What an evaluation found for one unmet step."""

    unit: str
    slug: str
    outcome: Outcome
    line: str = ""


def unmet_steps(unit: StoredUnit) -> list[ManualStep]:
    """The steps `unit` waits on."""
    return [step for step in unit.manual_steps if not step.done]


def manual_status_line(step: ManualStep) -> str:
    """The `abk status` words for an unmet step: its last line, or that its check failed."""
    if not step.outcome:
        said = "not checked yet"
    elif step.outcome in ("failed", "timeout"):
        said = f"check failed: {step.last_line}"
    else:
        said = step.last_line or "not done"
    runbook = f" (runbook: {step.runbook})" if step.runbook else ""
    return f"waiting for manual step {step.slug}: {said}{runbook}"


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return cut_head(redact_text(lines[-1], where="manual step check"), LINE_LIMIT, "char")


def _run(command: str, cwd: Path, seconds: int) -> tuple[Outcome, str]:
    try:
        process = subprocess.Popen(
            ["sh", "-c", command],
            cwd=cwd,
            env=_ENVIRONMENT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            # Its own group, so a timeout takes whatever the command started with it.
            start_new_session=True,
        )
    except OSError as error:
        return "failed", _last_line(f"could not run: {error}")
    try:
        out, err = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        return "timeout", f"timed out after {seconds} seconds"
    if process.returncode == 0:
        return "met", _last_line(out)
    if process.returncode < 0:
        return "failed", f"killed by signal {-process.returncode}"
    if line := _last_line(out):
        return "unmet", line
    return "failed", _last_line(err) or f"exited {process.returncode} and printed nothing"


def _directory(installation: Installation, unit: StoredUnit) -> Path:
    checkout = installation.checkouts[unit.repo]
    if not unit.branch:
        return checkout
    tree = worktree_path(checkout, unit.branch, installation.worktree_root)
    return tree if tree.is_dir() else checkout


def _check(installation: Installation, unit: StoredUnit, step: ManualStep) -> tuple[Outcome, str]:
    if not step.check:
        return "unmet", "no check declared"
    seconds = installation.config.global_limits.manual_check_seconds
    return _run(step.check, _directory(installation, unit), seconds)


def _removed(installation: Installation, unit: StoredUnit, step: ManualStep) -> None:
    """Take away the script a raised step was checked by, now the step it guards is done."""
    if not step.check.startswith(f"{MANUAL_FOLDER}/"):
        return
    script = _directory(installation, unit) / step.check
    if script.is_file() and not script.is_symlink():
        script.unlink()
        print(f"{unit.id}: manual step {step.slug} is done, removed {step.check}", flush=True)


def evaluate_manual_steps(
    installation: Installation, *, now: datetime, dry_run: bool = False, slug: str = ""
) -> list[ManualAction]:
    """Run the check of every unmet step of every waiting unit (only the step `slug` when
    given), record the result, and mark a passing step done. A unit whose last step is done gets
    a history entry that says so, which its readmission follows. With `dry_run` only report."""
    store = UnitStore(installation.state_dir / "units.json")
    actions: list[ManualAction] = []
    for unit in store.all():
        if unit.state != PLANNED:
            continue
        steps: Sequence[ManualStep] = unit.manual_steps
        for position, step in enumerate(steps):
            if step.done or (slug and step.slug != slug):
                continue
            outcome, line = _check(installation, unit, step)
            actions.append(ManualAction(unit=unit.id, slug=step.slug, outcome=outcome, line=line))
            if dry_run:
                continue
            changed = (outcome, line) != (step.outcome, step.last_line)
            recorded = step.model_copy(
                update={
                    "done": outcome == "met",
                    "outcome": outcome,
                    "last_line": line,
                    "checked_at": now,
                }
            )
            steps = [*steps[:position], recorded, *steps[position + 1 :]]
            store.set_manual_steps(unit.id, steps)
            if outcome == "met":
                _removed(installation, unit, step)
            if changed:
                said = "done" if outcome == "met" else (line or outcome)
                store.set_state(
                    unit.id,
                    PLANNED,
                    note=f"manual step {step.slug}: {said}",
                    cause=KEEP,
                )
    return actions
