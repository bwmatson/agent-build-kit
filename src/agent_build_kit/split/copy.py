"""Carrying a split plan out: files, unit records and plan records, checked before any write."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.split.select import SplitPlan

__all__ = ["CopyRefused", "CopyReport", "Preflight", "carry_out", "preflight"]


class CopyRefused(ValueError):
    """The preflight found errors; nothing was written."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


class Preflight(Frozen):
    """Every conflict and dangling edge (the errors) and every staying edge into the moved set
    (a warning, an error under `remove`), found before the first write."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class CopyReport(Frozen):
    files_copied: int = 0
    files_unchanged: int = 0
    units_imported: int = 0
    plans_written: int = 0


def preflight(
    source: Installation,
    destination: Installation,
    plan: SplitPlan,
    *,
    scrub: bool = False,
    remove: bool = False,
) -> Preflight:
    """What would refuse the copy, reading both installations and writing neither."""
    raise NotImplementedError


def carry_out(
    source: Installation,
    destination: Installation,
    plan: SplitPlan,
    *,
    scrub: bool = False,
) -> CopyReport:
    """Copy the plan's files, import its unit records and write its plan records;
    raises `CopyRefused` with every error and writes nothing when the preflight finds one."""
    raise NotImplementedError
