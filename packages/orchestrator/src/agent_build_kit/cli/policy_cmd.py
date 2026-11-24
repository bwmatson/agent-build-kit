"""`abk policy`: the kit's recommended policy for a build agent, printed and compared."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_build_kit import config as config_module
from agent_build_kit import runtimes
from agent_build_kit.config import ConfigError, RuntimeConfig
from agent_build_kit.init.runtime_choice import confirmed
from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.runtimes import AgentRuntime, known_agents, policy_apply, policy_check
from agent_build_kit.runtimes.guards import guard_lines
from agent_build_kit.runtimes.known_agents import ApplyPolicy, KnownAgent, agent_for_command
from agent_build_kit.runtimes.policy_apply import ApplyRefused, ApplyResult, Status
from agent_build_kit.runtimes.recommended_policy import (
    DIALECT,
    KNOWN_FALSE_POSITIVES,
    RECOMMENDED,
    UNCOVERED,
    patterns,
)


def cmd_policy_patterns(args: argparse.Namespace, installation: Installation | None) -> int:
    known = {policy.label: policy for policy in RECOMMENDED}
    unknown = [label for label in args.classes if label not in known]
    if unknown:
        print(
            f"abk: unknown class {', '.join(map(repr, unknown))}; the classes are: "
            + "; ".join(known),
            file=sys.stderr,
        )
        return 2
    extra: list[str] = []
    if args.extra:
        if installation is None:
            try:
                installation = load_installation(args.config)
            except ConfigError as error:
                print(f"abk: --extra needs an installation: {error}", file=sys.stderr)
                return 2
        entry = installation.config.runtimes.get(installation.config.runtime)
        extra = (entry.policy_extra if entry else None) or []
    for label in args.classes:
        if known[label].covered_by:
            print(
                f"abk: {label!r} has no globs of its own; {known[label].covered_by!r} covers it",
                file=sys.stderr,
            )
    globs = patterns(extra, args.classes)
    if args.format == "json":
        print(json.dumps(globs))
    elif args.format == "yaml-list":
        print("\n".join(f"- {json.dumps(g)}" for g in globs) if globs else "[]")
    elif globs:
        print("\n".join(globs))
    return 0


PATTERNS_COMMAND = "abk policy patterns"


class _Unresolved(Exception):
    """The agent cannot be chosen; the message says why and what to do."""


class _Usage(_Unresolved):
    """A name given on the command line that names nothing."""


class _Nothing(Exception):
    """The runtime starts no agent of the table whose configuration the kit would change."""


def _named(name: str) -> KnownAgent:
    """The known agent called `name`, or a usage problem naming the ones there are."""
    table = known_agents.KNOWN_AGENTS
    named = next((a for a in table if a.name.lower() == name.lower()), None)
    if named is None:
        known = ", ".join(agent.name for agent in table)
        raise _Usage(f"unknown agent {name!r}; the known agents are: {known}")
    return named


def _entry_for(installation: Installation, runtime: str | None) -> RuntimeConfig:
    """The entry of the runtime called `runtime`, or of the selected one when None; a usage
    problem naming the runtimes there are when it is not one."""
    configured = installation.config.runtimes
    if runtime and runtime not in (*runtimes.names(), *configured):
        known = ", ".join(sorted({*runtimes.names(), *configured}))
        raise _Usage(f"unknown runtime {runtime!r}; the runtimes are: {known}")
    return config_module.runtime_entry(installation.config, name=runtime)


def _agent_for(
    args: argparse.Namespace, installation: Installation | None
) -> tuple[KnownAgent, RuntimeConfig]:
    """The known agent the selected runtime starts, or the one `--agent` names, with the
    runtime's entry."""
    entry = RuntimeConfig()
    if installation is None:
        if not args.agent:
            raise _Unresolved(
                "no installation to read the runtime's command from; give --agent NAME"
            )
    else:
        entry = _entry_for(installation, args.runtime)
    if args.agent:
        return _named(args.agent), entry
    if not entry.command:
        raise _Nothing("its enforcement is built in or it starts no known agent")
    found = agent_for_command(entry.command)
    if found is None:
        raise _Unresolved(
            f"{entry.command[0]} is not a program of the known-agent table; name the agent "
            "with --agent NAME"
        )
    return found, entry


def _show_configuration(
    agent: KnownAgent, entry: RuntimeConfig, installation: Installation | None
) -> None:
    print(f"\nAgent configuration ({agent.name}):")
    descriptor = agent.apply
    if descriptor is None:
        print(
            f"  the kit cannot read {agent.name}'s configuration; run `{PATTERNS_COMMAND}` "
            "and add the globs to it yourself"
        )
        return
    home = policy_apply.resolve_home(descriptor, installation.env_file if installation else None)
    path = home / descriptor.file
    try:
        held = policy_apply.held(descriptor, home)
    except ApplyRefused as error:
        print(f"  {path} cannot be read: {error}")
        return
    if held is None:
        print(f"  {path}: no configuration there; the agent is not installed or its home is")
        print(f"  elsewhere (set {descriptor.home_env})")
        return
    print(f"  {path}")
    wanted = patterns(entry.policy_extra or [])
    missing = [glob for glob in wanted if glob not in held.deny]
    print(f"  recommended patterns present: {len(wanted) - len(missing)} of {len(wanted)}")
    for policy in RECOMMENDED:
        lacking = [glob for glob in policy.globs if glob in missing]
        if lacking:
            print(f"  missing, {policy.label}:")
            for glob in lacking:
                print(f"    {glob}")
    extras = [glob for glob in entry.policy_extra or [] if glob in missing]
    if extras:
        print("  missing, the installation's policy_extra:")
        for glob in extras:
            print(f"    {glob}")
    own = [entry for entry in held.deny if entry not in wanted]
    print(f"  entries that are not the kit's: {len(own)}")
    if descriptor.toolset:
        print(f"  toolset recommended: {list(descriptor.toolset.names)}")
        print(f"  toolset now: {list(held.toolset) if held.toolset is not None else 'none'}")
        print("  `abk policy apply --toolset` replaces it; apply alone leaves it")


def cmd_policy_show(args: argparse.Namespace, installation: Installation | None) -> int:
    for policy in RECOMMENDED:
        print(policy.label)
        for glob in policy.globs:
            print(f"  {glob}")
        if policy.covered_by:
            print(f"  (covered by the globs of: {policy.covered_by})")
    print("\nNot covered:")
    for uncovered in UNCOVERED:
        print(f"  {uncovered.label}: {uncovered.reason}")
    print("\nKnown false positives:")
    for command in KNOWN_FALSE_POSITIVES:
        print(f"  {command}")
    print(f"\nDialect: {DIALECT}")
    print("\nThe policy check is not run here; `abk policy check` or `abk doctor` runs it.")
    if installation is not None or args.runtime or args.agent:
        try:
            agent, entry = _agent_for(args, installation)
        except _Nothing:
            return 0
        except _Usage as error:
            print(f"abk: {error}", file=sys.stderr)
            return 2
        except _Unresolved as error:
            print(
                f"\nAgent configuration: not read: {error}; `{PATTERNS_COMMAND}` prints "
                "the globs to add to it yourself"
            )
            return 0
        _show_configuration(agent, entry, installation)
    return 0


def preview(
    descriptor: ApplyPolicy, home: Path, extra: list[str], toolset: bool
) -> ApplyResult | None:
    """What applying the recommended policy would do, or None after printing why it cannot be
    known: the configuration is refused or cannot be read."""
    try:
        return policy_apply.apply(descriptor, home, extra, toolset, dry_run=True)
    except (ApplyRefused, OSError) as error:
        print(f"abk: {error}", file=sys.stderr)
        return None


def write_recommended(
    descriptor: ApplyPolicy, home: Path, extra: list[str], toolset: bool
) -> ApplyResult | None:
    """Apply the recommended policy and say what was written, or None after printing why it
    could not be."""
    try:
        done = policy_apply.apply(descriptor, home, extra, toolset)
    except (ApplyRefused, OSError) as error:
        print(f"abk: {error}", file=sys.stderr)
        return None
    if done.backup:
        print(f"backed up the original to {done.backup}")
    print(f"added {len(done.added)} patterns to {done.path}")
    return done


def cmd_policy_apply(args: argparse.Namespace, installation: Installation | None) -> int:
    if args.dry_run and args.yes:
        print("abk: --dry-run writes nothing, so --yes has nothing to confirm", file=sys.stderr)
        return 2
    try:
        agent, entry = _agent_for(args, installation)
    except _Nothing as why:
        print(f"nothing to apply: {why}")
        return 0
    except _Unresolved as error:
        print(f"abk: {error}", file=sys.stderr)
        return 2
    descriptor = agent.apply
    if descriptor is None:
        print(
            f"abk: the kit cannot write {agent.name}'s configuration; run `{PATTERNS_COMMAND}` "
            "and add the globs to it yourself",
            file=sys.stderr,
        )
        return 2
    home = policy_apply.resolve_home(descriptor, installation.env_file if installation else None)
    extra = entry.policy_extra or []
    shown = preview(descriptor, home, extra, args.toolset)
    offered = (
        preview(descriptor, home, extra, True)
        if shown and descriptor.toolset and not args.toolset
        else shown
    )
    if shown is None or offered is None:
        return 2
    if shown.status == Status.ABSENT:
        print(f"abk: {shown.message}", file=sys.stderr)
        return 2
    if shown.status == Status.UNCHANGED:
        print(f"{shown.path}: {shown.message}")
    else:
        print(shown.diff, end="")
    if shown.toolset_change:
        before, after = shown.toolset_change
        print(f"toolset: from {list(before)} to {list(after)}")
    elif not args.toolset and offered.toolset_change:
        before, after = offered.toolset_change
        print(
            f"toolset: recommended {list(after)}, currently {list(before)}; left as it is "
            "(`abk policy apply --toolset` replaces it)"
        )
    if shown.status == Status.UNCHANGED or args.dry_run:
        return 0
    if not (args.yes or confirmed(f"apply to {shown.path}? [y/N] ")):
        print("not applied; nothing was written")
        return 1
    if write_recommended(descriptor, home, extra, args.toolset) is None:
        return 2
    print(
        "Whether the agent now refuses them is not checked here: `abk policy check` reads the "
        "configuration and spends no model tokens."
    )
    return 0


def coverage_line(runtime: AgentRuntime, installation: Installation) -> str:
    """The runtime's two coverages side by side; `abk status` prints the same line."""
    return (
        f"runtime {runtime.name}: policy_coverage: {runtime.policy_coverage}, "
        f"sandbox_coverage: {policy_check.sandbox_coverage_text(runtime, installation)}"
    )


def cmd_policy_check(args: argparse.Namespace, installation: Installation | None) -> int:
    """Judge every probe command against the agent's configuration and print the verdicts:
    exit 0 when every covered class is refused, 1 when not or when it could not be checked."""
    assert installation is not None  # the command needs one
    config = installation.config
    name = args.runtime or config_module.runtime_name(config)
    try:
        entry = _entry_for(installation, args.runtime)
        runtime = runtimes.get(name)
        if args.agent:
            # The named agent's configuration is judged whatever runtime is selected.
            entry = entry.model_copy(update={"command": [_named(args.agent).program]})
            runtime = runtimes.get(known_agents.RUNTIME_NAME)
    except _Usage as error:
        print(f"abk: {error}", file=sys.stderr)
        return 2
    print(coverage_line(runtime, installation))
    for line in guard_lines(runtime, installation):
        print(line)
    report = policy_check.check_policy(runtime, entry, installation)
    if report.cannot_check:
        print(report.cannot_check)
        return 1
    print("\n".join(policy_check.render(report)))
    if report.ok:
        print("every covered class is refused")
        return 0
    print(f"not refused: {policy_check.describe(report)}")
    print(f"fix: {policy_check.fix_for(name, entry, report)}")
    return 1


def _agent_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runtime", help="the runtime whose agent to read (default: the installation's)"
    )
    parser.add_argument(
        "--agent", help="the known agent's name, when the runtime's command is a wrapper"
    )


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("policy", help="the recommended policy for a build agent")
    commands = parser.add_subparsers(dest="policy_command", required=True)
    patterns = commands.add_parser("patterns", help="print the recommended command globs")
    patterns.add_argument(
        "--format",
        choices=("glob", "json", "yaml-list"),
        default="glob",
        help="one glob per line, a JSON array, or a YAML sequence (default: glob)",
    )
    patterns.add_argument(
        "--class",
        dest="classes",
        action="append",
        default=[],
        metavar="LABEL",
        help="only this class's globs; repeatable; the labels are those `abk policy show` prints",
    )
    patterns.add_argument(
        "--extra",
        action="store_true",
        help="add the selected runtime's `runtimes.<runtime>.policy_extra` (needs an installation)",
    )
    patterns.set_defaults(func=cmd_policy_patterns, needs_installation="optional")
    show = commands.add_parser("show", help="the recommendation, its gaps and its dialect")
    _agent_flags(show)
    show.set_defaults(func=cmd_policy_show, needs_installation="optional")
    apply = commands.add_parser("apply", help="merge the recommendation into the agent's config")
    _agent_flags(apply)
    apply.add_argument("--dry-run", action="store_true", help="print the diff and write nothing")
    apply.add_argument("--yes", action="store_true", help="apply without asking")
    apply.add_argument(
        "--toolset",
        action="store_true",
        help="also replace the agent's toolset with the recommended one (never done by default)",
    )
    apply.set_defaults(func=cmd_policy_apply, needs_installation="optional")
    check = commands.add_parser(
        "check", help="read the agent's configuration and say what it refuses; starts nothing"
    )
    _agent_flags(check)
    check.set_defaults(func=cmd_policy_check)
