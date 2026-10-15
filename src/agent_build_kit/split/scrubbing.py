"""The one seam between a split and the public-content scrub: the term list and the text pass."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import Description, StoredUnit, with_text
from agent_build_kit.scrub_terms import REPLACEMENT, scrub_text, terms_for
from agent_build_kit.split.select import SplitPlan, moved_files, moved_records

__all__ = [
    "ScrubCounts",
    "read_text",
    "scrub_counts",
    "scrub_record",
    "scrub_text",
    "scrubber",
    "terms_for",
]


class ScrubCounts(Frozen):
    """What `--scrub` would change: moved files, moved records and substitutions."""

    files: int = 0
    records: int = 0
    substitutions: int = 0


def scrubber(source: Installation, repo: str) -> Callable[[str], str]:
    """The text pass for what moves out of `repo`: the source's terms, the repo itself not one."""
    terms = terms_for(source, target=source.checkouts[repo])
    return lambda text: scrub_text(text, terms)


def read_text(path: Path) -> str | None:
    """The file's text, or None when it is not UTF-8 (such a file is never scrubbed)."""
    try:
        return path.read_bytes().decode()
    except UnicodeDecodeError:
        return None


def scrub_record(unit: StoredUnit, scrub: Callable[[str], str]) -> StoredUnit:
    """The record with its free text scrubbed; identifiers, state and timestamps are kept."""
    description = unit.description
    if description is not None:
        description = Description(
            summary=scrub(description.summary), changes=tuple(map(scrub, description.changes))
        )
    return with_text(unit, scrub).model_copy(update={"description": description})


def scrub_counts(source: Installation, plan: SplitPlan) -> ScrubCounts:
    """How many moved files and records the scrub would change, writing nothing."""
    scrub = scrubber(source, plan.repo)
    files = substitutions = 0
    for path in moved_files(source, plan):
        text = read_text(path)
        if text is not None and (scrubbed := scrub(text)) != text:
            files += 1
            substitutions += scrubbed.count(REPLACEMENT) - text.count(REPLACEMENT)
    records = 0
    for unit in moved_records(source, plan):
        if (changed := scrub_record(unit, scrub)) != unit:
            records += 1
            substitutions += _placeholders(changed) - _placeholders(unit)
    return ScrubCounts(files=files, records=records, substitutions=substitutions)


def _placeholders(unit: StoredUnit) -> int:
    return unit.model_dump_json().count(REPLACEMENT)
