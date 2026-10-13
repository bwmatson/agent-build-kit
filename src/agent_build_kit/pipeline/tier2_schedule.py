"""When each repo's whole tier 2 suite is due, and the change that asks for the run.

The schedule is stored nowhere: the last run of a repo is the latest date in the names of its
`scheduled-tier2-<repo>-<date>` changes, open or archived. The change is written without a
model, under a lock file, so two ticks write one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

from agent_build_kit.config import Tier2Schedule, tier2_schedule
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.unit_store import UnitStore

PREFIX = "scheduled-tier2"

PERIODS = {
    Tier2Schedule.DAILY: timedelta(days=1),
    Tier2Schedule.WEEKLY: timedelta(days=7),
    Tier2Schedule.MONTHLY: timedelta(days=30),
}

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ARCHIVED = re.compile(rf"{_DATE.pattern}-(?P<name>.+)")


def scheduled_name(repo: str, day: date) -> str:
    """The name of the change that runs `repo`'s suite, written on `day`."""
    return f"{PREFIX}-{repo}-{day.isoformat()}"


def scheduled_date(name: str, repo: str) -> date | None:
    """The date in `name` when it is a scheduled change of exactly `repo`, else None."""
    tail = name.removeprefix(f"{PREFIX}-{repo}-")
    if tail == name or not _DATE.fullmatch(tail):
        return None
    try:
        return date.fromisoformat(tail)
    except ValueError:
        return None


def write_due(
    inst: Installation, store: UnitStore, *, today: date, say: Callable[[str], None]
) -> list[str]:
    """Write the change of every due repo with none open, under the lock file: say
    `wrote: <change>`, or `exists: <change>` for a repo whose change is open. Returns the
    names written."""
    tier2_repos = {unit.repo for unit in store.all() if unit.tier == "tier2"}
    written: list[str] = []
    with file_lock(inst.state_dir / "scheduled-tier2.lock"):
        for repo, config in inst.repos.items():
            schedule = tier2_schedule(config, inst.config.limits)
            if repo not in tier2_repos or schedule is Tier2Schedule.OFF:
                continue
            opened = _open_changes(inst, repo)
            if opened:
                say(f"exists: {min(opened)}")
                continue
            latest = max(_archived_dates(inst, repo), default=None)
            if latest is not None and latest + PERIODS[schedule] > today:
                continue
            name = scheduled_name(repo, today)
            _write_change(inst, repo, name, today)
            say(f"wrote: {name}")
            written.append(name)
    return written


def _open_changes(inst: Installation, repo: str) -> list[str]:
    return [path.name for path in _children(inst.changes_dir) if scheduled_date(path.name, repo)]


def _archived_dates(inst: Installation, repo: str) -> list[date]:
    found = (_ARCHIVED.fullmatch(path.name) for path in _children(inst.changes_dir / "archive"))
    return [day for m in found if m and (day := scheduled_date(m["name"], repo))]


def _children(folder: Path) -> Iterable[Path]:
    return folder.iterdir() if folder.is_dir() else ()


def _write_change(inst: Installation, repo: str, name: str, today: date) -> None:
    root = inst.changes_dir / name
    root.mkdir(parents=True)
    # No spec: OpenSpec's strict validation wants a delta unless the change says it has none.
    (root / ".openspec.yaml").write_text("schema: spec-driven\nskip_specs: true\n")
    (root / "proposal.md").write_text(
        "## Why\n\n"
        f"The whole tier 2 suite of `{repo}` is due to run on its default branch "
        f"({today.isoformat()}). Units run only the tier 2 tests they add or change, so a "
        "break they do not touch is found here.\n\n"
        "## What Changes\n\n"
        f"- The tier 2 marker of `{repo}` runs whole on its default branch; a failing test is "
        "recorded and fixed by its own change.\n\n"
        "## Impact\n\n"
        f"- {repo}: nothing changes unless a test fails.\n"
    )
    (root / "design.md").write_text(
        "## Context\n\n"
        f"A scheduled run of the whole tier 2 suite of `{repo}`; the pipeline writes it and "
        "builds nothing.\n\n"
        "## Decisions\n\n"
        "- The unit runs the whole marker on the default branch and ends when it passes.\n"
    )
    (root / "tasks.md").write_text(
        "# Tasks\n\n"
        "Acceptance: none — the run of the suite is the check; nothing a consumer sees "
        "changes.\n\n"
        f"## 1. [{repo}] [tier2] Run the full tier 2 suite on the default branch\n\n"
        "Priority: 3\n\n"
        "Separate: a scheduled run has no code of its own and is never joined to other work.\n\n"
        "Done when the whole tier 2 marker passes on the default branch.\n\n"
        "- [ ] 1.1 Run the whole tier 2 marker on the default branch and record any failing "
        "test\n"
    )
