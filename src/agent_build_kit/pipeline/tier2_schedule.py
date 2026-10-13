"""When each repo's whole tier 2 suite is due, and the change that asks for the run.

The schedule is stored nowhere: the last run of a repo is the latest date in the names of its
`scheduled-tier2-<repo>-<date>` changes, open or archived.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore

PREFIX = "scheduled-tier2"


def scheduled_name(repo: str, day: date) -> str:
    """The name of the change that runs `repo`'s suite, written on `day`."""
    raise NotImplementedError


def scheduled_date(name: str, repo: str) -> date | None:
    """The date in `name` when it is a scheduled change of exactly `repo`, else None."""
    raise NotImplementedError


def write_due(
    inst: Installation, store: UnitStore, *, today: date, say: Callable[[str], None]
) -> list[str]:
    """Write the change of every due repo with none open, under the lock file: say
    `wrote: <change>`, or `exists: <change>` for a repo whose change is open. Returns the
    names written."""
    raise NotImplementedError
