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

from agent_build_kit.config import BASE_GROUP, Tier2Schedule, tier2_schedule, tier2_variants
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
_TAIL = re.compile(rf"(?P<date>{_DATE.pattern})(?:-(?P<variant>.+))?")
_ARCHIVED = re.compile(rf"{_DATE.pattern}-(?P<name>.+)")


def scheduled_name(repo: str, day: date, variant: str = BASE_GROUP) -> str:
    """The name of the change that runs `repo`'s `variant` group of the suite, written on `day`."""
    return f"{PREFIX}-{repo}-{day.isoformat()}-{variant}"


def is_scheduled(change: str) -> bool:
    """Whether `change` is a scheduled run of a repo's suite: the prefix is reserved."""
    return change.startswith(f"{PREFIX}-")


def scheduled_parts(name: str, repo: str, variants: Iterable[str]) -> tuple[date, str] | None:
    """The date and the variant in `name` when it is a scheduled change of exactly `repo` and
    one of `variants` (a name with no variant reads as `base`), else None."""
    tail = name.removeprefix(f"{PREFIX}-{repo}-")
    found = _TAIL.fullmatch(tail) if tail != name else None
    if not found:
        return None
    variant = found["variant"] or BASE_GROUP
    try:
        day = date.fromisoformat(found["date"])
    except ValueError:
        return None
    return (day, variant) if variant in set(variants) else None


def write_due(
    inst: Installation, store: UnitStore, *, today: date, say: Callable[[str], None]
) -> list[str]:
    """Write the change of every due repo and variant with none open, under the lock file:
    say `wrote: <change>`, or `exists: <change>` for a variant whose change is open. Returns
    the names written."""
    tier2_repos = {unit.repo for unit in store.all() if unit.tier == "tier2"}
    written: list[str] = []
    with file_lock(inst.state_dir / "scheduled-tier2.lock"):
        for repo, config in inst.repos.items():
            schedule = tier2_schedule(config, inst.config.global_limits)
            if repo not in tier2_repos or schedule is Tier2Schedule.OFF:
                continue
            variants = tier2_variants(config, inst.config)
            for variant in variants:
                opened = _open_changes(inst, repo, variant, variants)
                if opened:
                    say(f"exists: {min(opened)}")
                    continue
                latest = max(_archived_dates(inst, repo, variant, variants), default=None)
                if latest is not None and latest + PERIODS[schedule] > today:
                    continue
                name = scheduled_name(repo, today, variant)
                _write_change(inst, repo, name, today, variant)
                say(f"wrote: {name}")
                written.append(name)
    return written


def _open_changes(
    inst: Installation, repo: str, variant: str, variants: Iterable[str]
) -> list[str]:
    parsed = (
        (p.name, scheduled_parts(p.name, repo, variants)) for p in _children(inst.changes_dir)
    )
    return [name for name, parts in parsed if parts and parts[1] == variant]


def _archived_dates(
    inst: Installation, repo: str, variant: str, variants: Iterable[str]
) -> list[date]:
    found = (_ARCHIVED.fullmatch(path.name) for path in _children(inst.changes_dir / "archive"))
    parsed = (scheduled_parts(m["name"], repo, variants) for m in found if m)
    return [parts[0] for parts in parsed if parts and parts[1] == variant]


def _children(folder: Path) -> Iterable[Path]:
    return folder.iterdir() if folder.is_dir() else ()


def _write_change(inst: Installation, repo: str, name: str, today: date, variant: str) -> None:
    group = (
        "the tests of no runtime tag"
        if variant == BASE_GROUP
        else f"the `{variant}` runtime's tests"
    )
    root = inst.changes_dir / name
    root.mkdir(parents=True)
    # No spec: OpenSpec's strict validation wants a delta unless the change says it has none.
    (root / ".openspec.yaml").write_text("schema: spec-driven\nskip_specs: true\n")
    (root / "proposal.md").write_text(
        "## Why\n\n"
        f"The `{variant}` group of the tier 2 suite of `{repo}` ({group}) is due to run on its "
        f"default branch ({today.isoformat()}). Units run only the tier 2 tests they add or "
        "change, so a break they do not touch is found here.\n\n"
        "## What Changes\n\n"
        f"- The `{variant}` group of the tier 2 marker of `{repo}` runs whole on its default "
        "branch; a failing test is "
        "recorded and fixed by its own change.\n\n"
        "## Impact\n\n"
        f"- {repo}: nothing changes unless a test fails.\n"
    )
    (root / "design.md").write_text(
        "## Context\n\n"
        f"A scheduled run of the `{variant}` group of the tier 2 suite of `{repo}`; the pipeline "
        "writes it and "
        "builds nothing.\n\n"
        "## Decisions\n\n"
        f"- The unit runs the `{variant}` group on the default branch and ends when it passes.\n"
    )
    (root / "tasks.md").write_text(
        "# Tasks\n\n"
        "Acceptance: none — the run of the suite is the check; nothing a consumer sees "
        "changes.\n\n"
        f"## 1. [{repo}] [tier2] Run the `{variant}` group of the full tier 2 suite "
        "on the default branch\n\n"
        "Priority: 3\n\n"
        "Separate: a scheduled run has no code of its own and is never joined to other work.\n\n"
        f"Done when the `{variant}` group of the tier 2 marker passes on the default branch.\n\n"
        f"- [ ] 1.1 Run the `{variant}` group of the tier 2 marker on the default branch and "
        "record any failing test\n"
    )
