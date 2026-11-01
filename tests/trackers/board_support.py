"""What the wanted-board and reconciler tests share: a fixture change and the board sections."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.pipeline.units import Unit, UnitState
from agent_build_kit.trackers.config import TrackerSection, section_for
from tests.factories import unit as make_unit
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure

CHANGE = "lane-dedupe"
REPO_URL = "https://example.test/example/app/tree/main"
TYPES = {"epic": "Epic", "change": "Feature", "group": "Product Backlog Item", "task": "Task"}

PROPOSAL = """\
## Why

Lanes are filled twice when a rerun starts.

## What Changes

- The fill remembers the lanes it has seen.

## Impact

Nothing outside the fill.
"""
DESIGN = """\
## Context

Background nobody needs on the board.

## Decisions

**Remember lanes by key.** A lane is remembered under its key, and the first fill wins.
See docs/designs/lane-design.md#remembered-lanes for the longer argument.

## Risks

A risk nobody needs on the board.
"""
SPEC = """\
## ADDED Requirements

### Requirement: A lane is filled once

The fill SHALL fill each lane once.

#### Scenario: a rerun fills nothing (unit)

- **GIVEN** a filled lane
- **WHEN** the fill runs again
- **THEN** nothing is written

### Requirement: Conflicts are reported

A conflict SHALL be reported.

#### Scenario: a conflict is named (unit)

- **GIVEN** two lanes with one key
- **WHEN** the fill runs
- **THEN** the conflict is named
"""
TASKS = """\
# Remember lanes between runs

## 1. [app] [unit-test] Gap fill, conflicts and remembered lanes

Needs: base-change group 2 merged — the lane table

- [x] 1.1 Test: `tests/lanes/test_gap.py` — a gap is filled once. Verify: red.
- [ ] 1.2 Add the fill in `src/app/lanes.py`, covered by `tests/lanes/test_conflict.py`.
      Verify: 1.1 passes.

## 2. [app] [e2e-test] Report the lanes

- [ ] 2.1 Test: `tests/e2e/test_report.py` — the report lists each lane. Verify: red.
- [ ] 2.2 Add the report in `src/app/report.py`. Verify: 2.1 passes.
"""


def browse_example(path: str) -> str:
    """The address a host gives for `path` of the planning repo, in the fixtures' shape."""
    return f"{REPO_URL}/{path}"


def groups_tasks(count: int) -> str:
    """A `tasks.md` of `count` groups, each with a test task and an implementation task."""
    parts = ["# Remember lanes between runs\n"]
    for number in range(1, count + 1):
        parts.append(
            f"## {number}. [app] [unit-test] Group {number} work\n\n"
            f"- [ ] {number}.1 Test: `tests/lanes/test_{number}.py` — it works. Verify: red.\n"
            f"- [ ] {number}.2 Add the work in `src/app/lanes_{number}.py`. "
            f"Verify: {number}.1 passes.\n"
        )
    return "\n".join(parts)


def board_section(levels: Sequence[str], *, epic: bool = False) -> TrackerSection:
    configure(
        app={
            "kind": "azure_devops",
            "levels": list(levels),
            "epic": epic,
            "azure_devops": {**AZURE_BLOCK, "types": TYPES},
        }
    )
    section = section_for("app")
    assert section is not None
    return section


def write_change(
    changes_dir: Path,
    name: str = CHANGE,
    *,
    proposal: str = PROPOSAL,
    design: str = DESIGN,
    spec: str = SPEC,
    tasks: str = TASKS,
) -> None:
    folder = changes_dir / name
    (folder / "specs" / "lanes").mkdir(parents=True)
    (folder / "proposal.md").write_text(proposal)
    (folder / "design.md").write_text(design)
    (folder / "specs" / "lanes" / "spec.md").write_text(spec)
    (folder / "tasks.md").write_text(tasks)


def covering(uid: str, groups: tuple[int, ...], state: UnitState = UnitState.PLANNED) -> Unit:
    return make_unit(uid, change=CHANGE, groups=groups, state=state)
