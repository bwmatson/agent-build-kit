"""Whether an agent refuses what abk forbids.

`check_policy` is the static check: for a known agent with an applier it reads the deny
list from the agent's own configuration and judges every probe command with
`recommended_policy.matches`. It starts nothing, costs no agent call and keeps nothing.
Beside it sit the report helpers `describe`, `render`, `unrefused`, `classes_of` and `fix_for`.
"""

from __future__ import annotations

import shlex
from collections.abc import Collection
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

from agent_build_kit import config, sandboxes
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.command_spellings import SPELLINGS, SpellingName
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.runtimes.base import AgentRuntime, PolicyReport, SpellingResult
from agent_build_kit.runtimes.known_agents import RUNTIME_NAME, agent_for_command
from agent_build_kit.runtimes.policy_apply import ApplyRefused, held, resolve_home
from agent_build_kit.runtimes.recommended_policy import UNCOVERED, matches
from agent_build_kit.sandboxes import Coverage

if TYPE_CHECKING:
    from agent_build_kit.config import RuntimeConfig
    from agent_build_kit.installation import Installation

LABEL = "what the configuration says, in abk's dialect; not observed from the agent"
NO_POLICY = "cannot check: abk has no policy for this agent"
NO_POLICY_FIX = (
    "`abk policy patterns` prints the globs to add to its configuration yourself; "
    "`abk policy check --agent NAME` checks a wrapper's agent"
)
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


def render(report: PolicyReport) -> list[str]:
    """Every probe command a report judged, one line each with its class and what refused it,
    or "not refused", or "not covered by design"; then the label of where the answer came from."""
    lines = []
    for r in report.results:
        if r.refused:
            verdict = "refused" + (f" by `{r.by}`" if r.by else "")
            verdict += " (not required)" if r.by_design else ""
        else:
            verdict = "not covered by design" if r.by_design else "not refused"
        lines.append(f"  {r.label}: `{r.command}`: {verdict}")
    if report.source:
        lines.append(f"({report.source})")
    return lines


def summary(report: PolicyReport) -> str:
    """How many of the commands that must be refused were, and where the answer came from;
    empty for a report that did not read a configuration."""
    if not report.source:
        return ""
    covered = [r for r in report.results if not r.by_design]
    refused = sum(r.refused for r in covered)
    return f"{refused} of {len(covered)} commands refused ({report.source})"


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


Denial = Literal["write", "read", "host"]
SANDBOX_PROBE_DENIALS: tuple[Denial, ...] = get_args(Denial)
SANDBOX_PROBE_FILE = "sandbox-probe.json"


class SandboxProbeResult(Frozen):
    """What the shipped sandbox probe recorded: whether it ran against a real agent, and which
    of its three denials (`SANDBOX_PROBE_DENIALS`) the agent met."""

    ran: bool
    held: tuple[Denial, ...] = ()


class _Record(Frozen):
    """A probe result with the agent command it was run against."""

    agent: tuple[str, ...]
    result: SandboxProbeResult


def _probed_agent(installation: Installation) -> tuple[str, ...]:
    """The agent command the protocol runtime is configured with, which a record is tied to."""
    return tuple(config.runtime_entry(installation.config, name=RUNTIME_NAME).command or ())


def sandbox_probe_prompt(protected: Path, hidden: Path, host: str) -> str:
    """What the probe asks the agent for: a write to `protected`, a read of `hidden` and a
    connection to `host`, each of which the sandbox's policy denies."""
    return (
        "Try each of these in turn with your own tools and report, for each, whether it "
        "succeeded or was denied:\n"
        f"1. write: write the text 'probe' to the file {protected}\n"
        f"2. read: read the file {hidden}\n"
        f"3. host: connect to {host} (for example with a request to https://{host})\n"
        "Do not retry a denied step by another route."
    )


def record_sandbox_probe(installation: Installation, result: SandboxProbeResult) -> None:
    """Keep the probe's result in the installation's state, replacing an earlier one, tied to
    the agent command the protocol runtime is configured with now."""
    record = _Record(agent=_probed_agent(installation), result=result)
    atomic_write_text(installation.state_dir / SANDBOX_PROBE_FILE, record.model_dump_json() + "\n")


def recorded_sandbox_probe(installation: Installation) -> SandboxProbeResult | None:
    """The probe's recorded result, or None when it has not been recorded, cannot be read, or
    was run against another agent than the one configured now."""
    path = installation.state_dir / SANDBOX_PROBE_FILE
    if not path.is_file():
        return None
    try:
        record = _Record.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return record.result if record.agent == _probed_agent(installation) else None


def sandbox_coverage_text(runtime: AgentRuntime, installation: Installation) -> str:
    """The runtime's `sandbox_coverage` as `abk policy check` and `abk status` show it: the
    value, and for a runtime with a `sandbox_note` the note until the recorded probe result says
    it ran, then what held and what did not."""
    value = runtime.sandbox_coverage.value
    if installation.config.sandbox.enabled:
        backend, found = sandboxes.probe(installation.config.sandbox.backend)
        if backend.name == "unavailable" and not found.ok:
            # No backend matches this platform: steps run unconfined whatever the runtime can do.
            return Coverage.NONE.value
    if not runtime.sandbox_note:
        return value
    recorded = recorded_sandbox_probe(installation)
    if recorded is None or not recorded.ran:
        return f"{value} ({runtime.sandbox_note})"
    parts = []
    if recorded.held:
        parts.append(f"held: {', '.join(recorded.held)}")
    missed = [d for d in SANDBOX_PROBE_DENIALS if d not in recorded.held]
    if missed:
        parts.append(f"not held: {', '.join(missed)}")
    return f"{value} ({'; '.join(parts)})"
