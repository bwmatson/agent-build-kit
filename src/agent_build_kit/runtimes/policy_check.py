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
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from agent_build_kit.runtimes.base import AgentRuntime, PolicyReport, SpellingResult
from agent_build_kit.runtimes.known_agents import agent_for_command

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


def describe(report: PolicyReport, *, also: Collection[str] = ()) -> str:
    """What a report leaves open, one clause per forbidden class: the spellings
    not refused, then the class's other spellings as refused. `also` names classes
    to give even when every spelling is refused, so a fix's effect shows on the
    ones it closed. A report with no per-spelling results (one cached before they
    were kept) gives its labels."""
    classes: dict[str, list[SpellingResult]] = {}
    for result in report.results:
        classes.setdefault(result.label, []).append(result)
    clauses = []
    for label, results in classes.items():
        unrefused = [f"`{r.command}`" for r in results if not r.refused]
        if not unrefused and label not in also:
            continue
        refused = [f"`{r.command}`" for r in results if r.refused]
        clause = f"{label}:"
        if unrefused:
            clause += f" not refused as {', '.join(unrefused)}"
        if refused:
            clause += f"{';' if unrefused else ''} refused as {', '.join(refused)}"
        clauses.append(clause)
    return " | ".join(clauses) or ", ".join(report.unenforced)


def unrefused(report: PolicyReport) -> list[SpellingResult]:
    """The spellings a report found not refused, in table order."""
    return [r for r in report.results if not r.refused]


def classes_of(report: PolicyReport) -> set[str]:
    """The classes with a spelling not refused."""
    return {r.label for r in unrefused(report)}


def fix_for(name: str, entry: RuntimeConfig, report: PolicyReport) -> str:
    """What to tell an operator to run about an unenforced class: the installation's own
    `policy_fix` first, else the runtime's advice, else the kit's own: `abk policy apply` for
    an agent it can write to, else the patterns command and the key that would hold a fix."""
    own = shlex.join(entry.policy_fix) if entry.policy_fix else ""
    if not own and report.fix:
        return report.fix
    agent = agent_for_command(entry.command or [])
    if agent is not None and agent.apply is not None:
        return f"{own} or run `abk policy apply`" if own else "run `abk policy apply`"
    if own:
        return own
    return (
        "run `abk policy patterns` and add them to the agent's configuration, or "
        f"set `runtimes.{name}.policy_fix` in abk.yaml to what enforces them"
    )
