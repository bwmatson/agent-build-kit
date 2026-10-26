"""Test support: the suite does not read the checkout's `.env`.

A developer's ignored `.env` holds machine settings that a test asserting on defaults must not
see. It sits in the checkout, in the main working tree of the checkout's repository (a pipeline
worktree reads that one's file), or in the planning root the checkout resolves to (a unit
worktree has none of its own and stands in for the pipeline worktree).
"""

from collections.abc import Callable
from functools import cache
from pathlib import Path

from agent_build_kit.config import ConfigError, locate
from agent_build_kit.pipeline.planning_repo import main_working_tree
from tests.tracked_files import ROOT

ABSENT = ".env.absent-in-tests"


@cache
def checkout_roots(checkout: Path) -> frozenset[Path]:
    """The roots whose `.env` is the checkout's: itself, its repository's main working tree and
    the root `abk` resolves to from it."""
    roots = {checkout.resolve()}
    main = main_working_tree(checkout)
    if main is not None:
        roots.add(main.resolve())
    try:
        roots.add(locate(cwd=checkout).parent)
    except ConfigError:
        pass
    return frozenset(roots)


def without_checkout_env(
    lookup: Callable[[Path], Path], checkout: Path = ROOT
) -> Callable[[Path], Path]:
    """`lookup` (the environment-file lookup) answering a path that does not exist for the
    checkout's roots, and as before for any other root."""
    own = checkout_roots(checkout.resolve())

    def isolated(root: Path) -> Path:
        if root.resolve() in own:
            return checkout / ABSENT
        return lookup(root)

    return isolated
