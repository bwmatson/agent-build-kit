"""Whether the active runtime refuses what abk forbids, asked at most once a
short while.

`check_policy` may cost an agent call (a probe run), and `doctor` and `init`
ask it every time they run, so an answer is kept in a file beside the usage
reading and reused while it is fresh. A caller that has just changed what the
answer depends on — `init`, after running the installation's fix — asks for a
fresh one.
"""

from __future__ import annotations

import json
import os
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from agent_build_kit.runtimes.base import AgentRuntime, PolicyReport, SpellingResult

if TYPE_CHECKING:
    from agent_build_kit.config import RuntimeConfig
    from agent_build_kit.installation import Installation

# The cache's file name in the planning repo's state directory.
CACHE_NAME = "policy-check.json"

# How long an answer is reused before the runtime is asked again.
MAX_AGE = timedelta(minutes=15)


def checked(
    runtime: AgentRuntime,
    cwd: Path,
    *,
    cache: Path,
    now: datetime | None = None,
    fresh: bool = False,
) -> PolicyReport:
    """`runtime.check_policy(cwd)`, or the answer it gave within `MAX_AGE`.

    Answers are kept per runtime, so switching runtimes never reuses the
    other's. An unreadable cache is a cache miss."""
    now = now or datetime.now(UTC)
    try:
        kept = json.loads(cache.read_text())
        if not isinstance(kept, dict):
            kept = {}
    except (OSError, ValueError):
        kept = {}

    if not fresh:
        try:
            entry = kept[runtime.name]
            if now - datetime.fromisoformat(entry["checked_at"]) < MAX_AGE:
                return PolicyReport.model_validate(entry["report"])
        except (KeyError, TypeError, ValueError):
            pass  # Nothing usable kept for this runtime: ask it.

    report = runtime.check_policy(cwd)
    kept[runtime.name] = {"checked_at": now.isoformat(), "report": report.model_dump(mode="json")}
    cache.parent.mkdir(parents=True, exist_ok=True)
    # Written aside and moved into place, so a doctor and an init running at
    # once never read half a file.
    partial = cache.with_name(f".{cache.name}.{os.getpid()}.tmp")
    partial.write_text(json.dumps(kept, indent=2))
    os.replace(partial, cache)
    return report


def cache_path(inst: Installation) -> Path:
    """Where `doctor` and `init` alike keep the answer."""
    return inst.state_dir / CACHE_NAME


def describe(report: PolicyReport) -> str:
    """What a report leaves open, one clause per forbidden class: the spellings
    not refused, then the class's other spellings as refused. A report with no
    per-spelling results (one cached before they were kept) gives its labels."""
    classes: dict[str, list[SpellingResult]] = {}
    for result in report.results:
        classes.setdefault(result.label, []).append(result)
    clauses = []
    for label, results in classes.items():
        unrefused = [f"`{r.command}`" for r in results if not r.refused]
        if not unrefused:
            continue
        clause = f"{label}: not refused as {', '.join(unrefused)}"
        refused = [f"`{r.command}`" for r in results if r.refused]
        if refused:
            clause += f"; refused as {', '.join(refused)}"
        clauses.append(clause)
    return " | ".join(clauses) or ", ".join(report.unenforced)


def fix_for(name: str, entry: RuntimeConfig, report: PolicyReport) -> str:
    """What to tell an operator to run about an unenforced class: the
    installation's own `policy_fix`, else the runtime's advice, else the key
    that would hold one."""
    if entry.policy_fix:
        return shlex.join(entry.policy_fix)
    return report.fix or f"set `runtimes.{name}.policy_fix` in abk.yaml to what enforces them"
