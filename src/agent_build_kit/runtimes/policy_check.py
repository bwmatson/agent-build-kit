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
import shlex
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from agent_build_kit.pipeline.command_spellings import SPELLINGS, SpellingName
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.runtimes.base import AgentRuntime, PolicyReport, SpellingResult
from agent_build_kit.runtimes.known_agents import RUNTIME_NAME, agent_for_command
from agent_build_kit.runtimes.policy_apply import ApplyRefused, held, resolve_home
from agent_build_kit.runtimes.recommended_policy import UNCOVERED, matches

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
    # Written whole, so a doctor and an init running at once never read half a file.
    atomic_write_text(cache, json.dumps(kept, indent=2))
    return report


LABEL = "what the configuration says, in abk's dialect; not observed from the agent"
NO_POLICY = "cannot check: abk has no policy for this agent"
UNCOVERED_LABELS = frozenset(u.label for u in UNCOVERED)


def _cannot(reason: str) -> PolicyReport:
    return PolicyReport(ok=False, cannot_check=reason, source=LABEL)


def check_policy(
    runtime: AgentRuntime, entry: RuntimeConfig, installation: Installation
) -> PolicyReport:
    """Whether the agent's own configuration refuses what abk forbids, judged with the
    kit's matcher (`recommended_policy.matches`) over every command the probe lists.

    A runtime that is not the protocol one answers on its own. The agent is never started,
    and nothing is kept: every call reads the file again."""
    if runtime.name != RUNTIME_NAME:
        return runtime.check_policy(installation.root)
    agent = agent_for_command(entry.command or [])
    if agent is None or agent.apply is None:
        return _cannot(NO_POLICY)
    descriptor = agent.apply
    home = resolve_home(descriptor, installation.env_file)
    try:
        found = held(descriptor, home)
    except ApplyRefused as exc:
        return _cannot(str(exc))
    if found is None:
        return _cannot(
            f"no configuration at {home / descriptor.file}; the agent is not installed or "
            f"its home is elsewhere (set {descriptor.home_env})"
        )

    from agent_build_kit.runtimes.acp import PROBE_CLASSES  # needs the protocol library

    spelled = {s.command: s.name.value for rows in SPELLINGS.values() for s in rows}
    results = []
    for command, label in PROBE_CLASSES:
        by = next((p for p in found.deny if matches(p, command)), "")
        results.append(
            SpellingResult(
                label=label,
                spelling=spelled.get(command, SpellingName.PLAIN.value),
                command=command,
                refused=bool(by),
                by=by,
                by_design=label in UNCOVERED_LABELS,
            )
        )
    # A plain spelling not refused reads as its class; another names itself.
    unenforced = tuple(
        r.label if r.spelling == SpellingName.PLAIN else f"{r.label} (as {r.command})"
        for r in results
        if not r.refused and not r.by_design
    )
    return PolicyReport(
        ok=not unenforced, unenforced=unenforced, results=tuple(results), source=LABEL
    )


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
        unrefused = [f"`{r.command}`" for r in results if not r.refused and not r.by_design]
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
    """The spellings a report found not refused, in table order; a class the recommendation
    leaves to the person is not among them."""
    return [r for r in report.results if not r.refused and not r.by_design]


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
