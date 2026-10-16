"""When each repo's whole tier 2 suite is due, and the change that asks for the run.

The schedule is stored nowhere: the last run of a repo is the latest date in the names of its
`scheduled-tier2-<repo>-<date>-<split>` changes, open or archived. The change is written without a
model, under a lock file, so two ticks write one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

from agent_build_kit.config import (
    BASE_GROUP,
    REST_SPLIT,
    Tier2Schedule,
    tier2_schedule,
    tier2_splits,
)
from agent_build_kit.installation import Installation
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.unit_store import UnitStore

PREFIX = "scheduled-tier2"

PERIODS = {
    Tier2Schedule.DAILY: timedelta(days=1),
    Tier2Schedule.WEEKLY: timedelta(days=7),
    Tier2Schedule.MONTHLY: timedelta(days=30),
}

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TAIL = re.compile(rf"(?P<date>{_DATE.pattern})(?:-(?P<split>.+))?")
_ARCHIVED = re.compile(rf"{_DATE.pattern}-(?P<name>.+)")


def scheduled_name(repo: str, day: date, split: str = REST_SPLIT) -> str:
    """The name of the change that runs `repo`'s `split` of the suite, written on `day`."""
    return f"{PREFIX}-{repo}-{day.isoformat()}-{split}"


def is_scheduled(change: str) -> bool:
    """Whether `change` is a scheduled run of a repo's suite: the prefix is reserved."""
    return change.startswith(f"{PREFIX}-")


def _parts(name: str, repo: str) -> tuple[str, str] | None:
    """The date text and the split in `name` when it is a scheduled change of exactly `repo`
    (a name with no split, or ending `-base`, reads as `rest`), else None."""
    tail = name.removeprefix(f"{PREFIX}-{repo}-")
    found = _TAIL.fullmatch(tail) if tail != name else None
    if not found:
        return None
    split = found["split"]
    return found["date"], REST_SPLIT if split in (None, BASE_GROUP) else split


def scheduled_parts(name: str, repo: str, splits: Iterable[str]) -> tuple[date, str] | None:
    """The date and the split in `name` when it is a scheduled change of exactly `repo` and
    one of `splits` (a name with no split, or ending `-base`, reads as `rest`), else None."""
    parts = _parts(name, repo)
    if parts is None:
        return None
    try:
        day = date.fromisoformat(parts[0])
    except ValueError:
        return None
    return (day, parts[1]) if parts[1] in set(splits) else None


def scheduled_split(name: str, repo: str) -> str:
    """The split a scheduled change of `repo` runs, read from its name (`rest` when the name
    carries none, or `base`)."""
    parts = _parts(name, repo)
    return REST_SPLIT if parts is None else parts[1]


def write_due(
    inst: Installation,
    store: UnitStore,
    *,
    today: date,
    say: Callable[[str], None],
    dry_run: bool = False,
    say_existing: bool = True,
) -> list[str]:
    """Write the change of every due repo and split with none open, under the lock file: say
    `wrote: <change>`, or `exists: <change>` for a split whose change is open. A dry run writes
    nothing and says `would write: <change>`. `say_existing` False leaves out the `exists:`
    lines, for rounds that repeat. Returns the names written (or to be written)."""
    written: list[str] = []
    with file_lock(inst.state_dir / "scheduled-tier2.lock"):
        for repo, split, opened in _scheduled_repos(inst, store, today):
            if opened:
                if say_existing:
                    say(f"exists: {opened}")
                continue
            name = scheduled_name(repo, today, split)
            if dry_run:
                say(f"would write: {name}")
            else:
                _write_change(inst, repo, name, today, split)
                say(f"wrote: {name}")
            written.append(name)
    return written


def any_due(inst: Installation, store: UnitStore, *, today: date) -> bool:
    """Whether a split is due and has no open change: a round would write one."""
    return any(not opened for _, _, opened in _scheduled_repos(inst, store, today))


def _scheduled_repos(
    inst: Installation, store: UnitStore, today: date
) -> list[tuple[str, str, str | None]]:
    """Each split that is open (its open change's name) or due (None), in the config's order."""
    tier2_repos = {unit.repo for unit in store.all() if unit.tier == TestTier.E2E_TEST}
    found: list[tuple[str, str, str | None]] = []
    for repo, config in inst.repos.items():
        schedule = tier2_schedule(config, inst.config.global_limits)
        if repo not in tier2_repos or schedule is Tier2Schedule.OFF:
            continue
        splits = [split.name for split in tier2_splits(config, inst.config)]
        for split in splits:
            opened = _open_changes(inst, repo, split, splits)
            if opened:
                found.append((repo, split, min(opened)))
                continue
            latest = max(_archived_dates(inst, repo, split, splits), default=None)
            if latest is None or latest + PERIODS[schedule] <= today:
                found.append((repo, split, None))
    return found


def _open_changes(inst: Installation, repo: str, split: str, splits: Iterable[str]) -> list[str]:
    parsed = ((p.name, scheduled_parts(p.name, repo, splits)) for p in _children(inst.changes_dir))
    return [name for name, parts in parsed if parts and parts[1] == split]


def _archived_dates(inst: Installation, repo: str, split: str, splits: Iterable[str]) -> list[date]:
    found = (_ARCHIVED.fullmatch(path.name) for path in _children(inst.changes_dir / "archive"))
    parsed = (scheduled_parts(m["name"], repo, splits) for m in found if m)
    return [parts[0] for parts in parsed if parts and parts[1] == split]


def _children(folder: Path) -> Iterable[Path]:
    return folder.iterdir() if folder.is_dir() else ()


def _write_change(inst: Installation, repo: str, name: str, today: date, split: str) -> None:
    group = (
        "the tests of no declared split"
        if split == REST_SPLIT
        else f"the tests the `{split}` split's marker selects"
    )
    root = inst.changes_dir / name
    root.mkdir(parents=True)
    # No spec: OpenSpec's strict validation wants a delta unless the change says it has none.
    (root / ".openspec.yaml").write_text("schema: spec-driven\nskip_specs: true\n")
    (root / "proposal.md").write_text(
        "## Why\n\n"
        f"The `{split}` split of the tier 2 suite of `{repo}` ({group}) is due to run on its "
        f"default branch ({today.isoformat()}). Units run only the tier 2 tests they add or "
        "change, so a break they do not touch is found here.\n\n"
        "## What Changes\n\n"
        f"- The `{split}` split of the tier 2 marker of `{repo}` runs whole on its default "
        "branch; a failing test is "
        "recorded and fixed by its own change.\n\n"
        "## Impact\n\n"
        f"- {repo}: nothing changes unless a test fails.\n"
    )
    (root / "design.md").write_text(
        "## Context\n\n"
        f"A scheduled run of the `{split}` split of the tier 2 suite of `{repo}`; the pipeline "
        "writes it and "
        "builds nothing.\n\n"
        "## Decisions\n\n"
        f"- The unit runs the `{split}` split on the default branch and ends when it passes.\n"
    )
    (root / "tasks.md").write_text(
        "# Tasks\n\n"
        "Acceptance: none — the run of the suite is the check; nothing a consumer sees "
        "changes.\n\n"
        f"## 1. [{repo}] [{TestTier.E2E_TEST}] Run the `{split}` split of the full tier 2 suite "
        "on the default branch\n\n"
        "Priority: 3\n\n"
        "Separate: a scheduled run has no code of its own and is never joined to other work.\n\n"
        f"Done when the `{split}` split of the tier 2 marker passes on the default branch.\n\n"
        f"- [ ] 1.1 Run the `{split}` split of the tier 2 marker on the default branch and "
        "record any failing test\n"
    )
