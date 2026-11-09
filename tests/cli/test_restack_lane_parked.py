"""A unit with a parked thread whose branch is checked out in its own worktree.

The lane cannot move a branch that is checked out, and has no resolver call to spend on it:
it leaves the move for the unit's own run, which `resumable_units` then offers.
"""

from __future__ import annotations

OWED = "feature/3"
BRANCH = "spec/feature/3"
