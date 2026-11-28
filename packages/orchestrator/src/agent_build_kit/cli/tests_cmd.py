"""`abk tests report`: the five figures of a repository's tests."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.suite_shape import ShapeReport, definition, shape_report

# The window's default length, in days.
DEFAULT_WINDOW_DAYS = 7


def _percent(part: int | None, whole: int | None) -> str:
    return f"{round(100 * part / whole)}%" if part is not None and whole else "n/a"


def figure_lines(report: ShapeReport) -> list[str]:
    """The five figures of `report`, each a number line and its definition."""
    refused = f"unsupported by profile {report.unsupported_profile}"
    unsupported = report.unsupported_profile is not None
    ratio = (
        f"{report.added / report.modified:.2f} added per modified"
        if report.modified
        else "no ratio without a modified test"
    )
    values = [
        refused
        if unsupported
        else f"{report.unplaced} of {report.unit_test_files} unit-test files are not the "
        "test_<module> file of a source module",
        refused
        if unsupported
        else f"{report.new_files_not_for_new_module} of {report.new_files} new unit-test files "
        f"({_percent(report.new_files_not_for_new_module, report.new_files)}) are not for a "
        "new source module",
        refused
        if unsupported
        else f"{report.added} tests added, {report.modified} modified ({ratio})",
        refused
        if unsupported
        else f"{report.sharing} of {report.tests_read} tests share setup and action with a "
        f"sibling; {report.single_assertion} of {report.tests_read} "
        f"({_percent(report.single_assertion, report.tests_read)}) have exactly one assertion",
        (
            f"tests and files unsupported by profile {report.unsupported_profile}; "
            if unsupported
            else f"{report.tests_read} tests in {report.unit_test_files} unit-test files; "
        )
        + (
            f"median whole-suite run {report.median_minutes:.1f} minutes over "
            f"{report.full_runs} runs"
            if report.median_minutes is not None
            else "no whole-suite run in the ledger in the window"
        ),
    ]
    lines = [f"{report.repo}:"]
    for number, value in enumerate(values, start=1):
        lines += [f"  {number}. {value}", f"     {definition(number)}"]
    if report.left_out:
        lines.append(f"  not read: {', '.join(report.left_out)}")
    if report.unreadable:
        lines.append(f"  {report.unreadable} files could not be parsed")
    return lines


def cmd_tests_report(
    args: argparse.Namespace, installation: Installation | None, *, now: datetime | None = None
) -> int:
    """Print the figures of `args.repo` (every repository when None) from `args.since` (seven
    days before `now` when None); non-zero for an unknown repository or a date that does not
    parse."""
    assert installation is not None
    now = now or datetime.now(UTC)
    if args.since is None:
        since = (now - timedelta(days=DEFAULT_WINDOW_DAYS)).date()
    else:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(f"abk: {args.since!r} is not a date (use YYYY-MM-DD)", file=sys.stderr)
            return 2
    known = list(installation.config.repos)
    if args.repo is not None and args.repo not in known:
        print(
            f"abk: {args.repo!r} is not a configured repository (configured: {', '.join(known)})",
            file=sys.stderr,
        )
        return 2
    for name in [args.repo] if args.repo else known:
        for line in figure_lines(shape_report(installation, name, since=since, now=now)):
            print(line)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("tests", help="the shape of a repository's tests")
    commands = parser.add_subparsers(dest="tests_command", required=True)
    report = commands.add_parser("report", help="the five figures of a repository's tests")
    report.add_argument("--repo", help="the repository (default: every one)")
    report.add_argument("--since", help="the window's start, YYYY-MM-DD (default: 7 days ago)")
    report.set_defaults(func=cmd_tests_report)
