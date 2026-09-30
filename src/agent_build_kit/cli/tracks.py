"""`abk track`: run one of the scheduled tracks now, for every eligible repo
or just one."""

from __future__ import annotations

import argparse

from agent_build_kit.installation import Installation
from agent_build_kit.tracks.runner import PHASES, run_track


def cmd_track(args: argparse.Namespace, inst: Installation) -> int:
    return run_track(inst, args.phase, only=args.project, focus=args.focus, dry_run=args.dry_run)


def register(sub: argparse._SubParsersAction) -> None:
    track = sub.add_parser(
        "track",
        help="run a scheduled track (health, improve, recommend) or the propose pass now",
    )
    track.add_argument(
        "phase",
        choices=PHASES,
        help="'health': daily read-only pulse check. 'improve': weekly discovery + one "
        "propose pass that may write a change. 'recommend': weekly bigger-picture discovery "
        "+ one propose pass for the rare bounded finding. 'propose': standalone — turn the "
        "existing backlog into a change (see --focus). Each runs once per eligible repo. "
        "A track never edits a repo: it writes a change, and the pipeline builds it.",
    )
    track.add_argument(
        "--project",
        default=None,
        metavar="NAME",
        help="only this repo (an abk.yaml `repos` key) instead of every eligible one",
    )
    track.add_argument(
        "--focus",
        default=None,
        help="implement only: which backlog entries to read first — a track name "
        "(that track's most recent run log for the repo) or a run id",
    )
    track.add_argument(
        "--dry-run",
        action="store_true",
        help="print each rendered prompt's opening lines and the claude command, "
        "without the usage check, the pulls, or running claude",
    )
    track.set_defaults(func=cmd_track)
