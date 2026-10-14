"""The one seam between a split and the public-content scrub: the term list and the text pass."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.scrub_terms import scrub_text, terms_for
from agent_build_kit.split.select import SplitPlan

__all__ = ["ScrubCounts", "scrub_counts", "scrub_text", "terms_for"]


class ScrubCounts(Frozen):
    """What `--scrub` would change: moved files, moved records and substitutions."""

    files: int = 0
    records: int = 0
    substitutions: int = 0


def scrub_counts(source: Installation, plan: SplitPlan) -> ScrubCounts:
    """How many moved files and records the scrub would change, writing nothing."""
    raise NotImplementedError
