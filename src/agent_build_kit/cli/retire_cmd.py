"""`abk retire`: end a unit that has not finished.

Spec: a-started-unit-keeps-its-groups.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from agent_build_kit.installation import Installation


def retire(
    inst: Installation,
    unit_id: str,
    *,
    say: Callable[..., None],
    reason: str = "",
    delete_branch: bool = False,
    discard_unpushed: bool = False,
    dry_run: bool = False,
) -> int:
    """Retire `unit_id`; every message goes to `say(text, error=...)`. The result is the
    command's exit code: 0 done, 1 refused or partly done, 2 for an unknown unit."""
    raise NotImplementedError


def cmd_retire(args: argparse.Namespace, inst: Installation) -> int:
    """End a unit that has not finished, release its groups, close its pull request and keep
    its branch unless asked."""
    raise NotImplementedError
