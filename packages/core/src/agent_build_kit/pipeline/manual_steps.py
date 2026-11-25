"""Running the checks of the manual steps units wait on, each tick pass (spec: manual-steps).

A check is a command run in the unit's worktree under a timeout, with no agent and no usage
reading. An exit status of 0 marks the step done, for good; anything else, an error or a timeout
leaves it unmet and records why. The result is kept on the step, and a changed one is also a
history entry of the unit.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from agent_build_kit.budget import cut_head
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.unit_store import KEEP, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED, ManualStep
from agent_build_kit.pipeline.workspaces import unit_tree
from agent_build_kit.redaction import redact_text

# Where a builder writes the check script of a step it raises, in its worktree.
MANUAL_FOLDER = ".abk/manual"
# The longest line of a check's output that is kept.
LINE_LIMIT = 300
# All a check is given of the environment: it reads the repository, not the machine's secrets.
CHECK_ENVIRONMENT = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}

Outcome = Literal["met", "unmet", "failed", "timeout"]


class ManualAction(Frozen):
    """What an evaluation found for one unmet step."""

    unit: str
    slug: str
    outcome: Outcome
    line: str = ""
    # Whether the result differs from the one stored on the step before this pass.
    changed: bool


class Repeat(Frozen):
    """How many checks in a row gave one step the same result, and when the first of them ran."""

    result: tuple[str, str]
    count: int
    since: datetime


# The record of repeats, under the state dir, and the lock its writers take.
REPEATS_NAME = "manual-repeats.json"
REPEATS_LOCK = "manual-repeats.lock"


def _repeats_path(installation: Installation) -> Path:
    return installation.state_dir / REPEATS_NAME


def read_repeats(installation: Installation) -> dict[str, Repeat]:
    """The recorded repeats, keyed `<unit>/<slug>`; empty when there is no record."""
    try:
        raw = json.loads(_repeats_path(installation).read_text())
        return {key: Repeat.model_validate(value) for key, value in raw.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def repeat_note(repeat: Repeat | None, when: Callable[[datetime], str]) -> str:
    """The words `abk status` adds for a step whose last checks agreed; empty for one check.
    `when` writes the time of the first of them as the status writes its times."""
    if repeat is None or repeat.count < 2:
        return ""
    return f"same result for {repeat.count} checks since {when(repeat.since)}"


def _record_repeats(
    installation: Installation, actions: list[ManualAction], store: UnitStore, now: datetime
) -> None:
    """Count this pass's results against the record and drop what no longer waits."""
    waiting = {
        f"{unit.id}/{step.slug}"
        for unit in store.all()
        if unit.state == PLANNED
        for step in unmet_steps(unit)
        if step.check
    }
    with file_lock(installation.state_dir / REPEATS_LOCK):
        records = {k: v for k, v in read_repeats(installation).items() if k in waiting}
        for action in actions:
            key = f"{action.unit}/{action.slug}"
            if key not in waiting:
                continue
            result = (action.outcome, action.line)
            before = records.get(key)
            if before is not None and before.result == result:
                records[key] = before.model_copy(update={"count": before.count + 1})
            else:
                records[key] = Repeat(result=result, count=1, since=now)
        text = json.dumps({k: v.model_dump(mode="json") for k, v in records.items()}, indent=1)
        atomic_write_text(_repeats_path(installation), text)


def unmet_steps(unit: StoredUnit) -> list[ManualStep]:
    """The steps `unit` waits on."""
    return [step for step in unit.manual_steps if not step.done]


def manual_status_line(step: ManualStep, note: str = "") -> str:
    """The `abk status` words for an unmet step: its last line, or that its check failed, and
    `note` (see `repeat_note`) when given."""
    if not step.check:
        said = f"waiting for attestation: abk manual done {step.slug}"
    elif not step.outcome:
        said = "not checked yet"
    elif step.outcome in ("failed", "timeout"):
        said = f"check failed: {step.last_line}"
    else:
        said = step.last_line or "not done"
    if note:
        said = f"{said} ({note})"
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
            env=CHECK_ENVIRONMENT,
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
    return unit_tree(checkout, unit.branch, installation.worktree_root) or checkout


def _check(installation: Installation, unit: StoredUnit, step: ManualStep) -> tuple[Outcome, str]:
    if not step.check:
        return "unmet", "waits for attestation: abk manual done"
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


def replace_step(store: UnitStore, unit_id: str, recorded: ManualStep) -> bool:
    """Write `recorded` over the step of the same slug in the unit as the store holds it now,
    leaving the other steps as they are, so a writer holding an older read cannot undo what
    another wrote meanwhile. False, with nothing written, when that step is already done (a
    person attested it while a check ran) or is gone."""
    current = store.get(unit_id).manual_steps
    if not any(s.slug == recorded.slug and not s.done for s in current):
        return False
    store.set_manual_steps(unit_id, [recorded if s.slug == recorded.slug else s for s in current])
    return True


def evaluate_manual_steps(
    installation: Installation,
    store: UnitStore,
    *,
    now: datetime,
    dry_run: bool = False,
    slug: str = "",
) -> list[ManualAction]:
    """Run the check of every unmet step of every waiting unit in `store` (only the step `slug`
    when given), record the result, and mark a passing step done. A unit whose last step is done
    gets a history entry that says so, which its readmission follows. With `dry_run` only
    report."""
    actions: list[ManualAction] = []
    for unit in store.all():
        if unit.state != PLANNED:
            continue
        for step in unit.manual_steps:
            if step.done or (slug and step.slug != slug):
                continue
            outcome, line = _check(installation, unit, step)
            changed = (outcome, line) != (step.outcome, step.last_line)
            actions.append(
                ManualAction(
                    unit=unit.id, slug=step.slug, outcome=outcome, line=line, changed=changed
                )
            )
            if dry_run:
                continue
            if not step.check and not changed:
                continue
            recorded = step.model_copy(
                update={
                    "done": outcome == "met",
                    "outcome": outcome,
                    "last_line": line,
                    "checked_at": now,
                }
            )
            if not replace_step(store, unit.id, recorded):
                continue
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
    if not dry_run:
        _record_repeats(installation, actions, store, now)
    return actions
