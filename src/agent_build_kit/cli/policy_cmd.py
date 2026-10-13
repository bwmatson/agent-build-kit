"""`abk policy`: the kit's recommended policy for a build agent, printed and compared."""

from __future__ import annotations

import argparse
import json
import sys

from agent_build_kit.config import ConfigError
from agent_build_kit.installation import Installation, load_installation
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
    print("\nThe policy check is not run here; `abk doctor` runs it.")
    return 0


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
    show.set_defaults(func=cmd_policy_show, needs_installation="optional")
