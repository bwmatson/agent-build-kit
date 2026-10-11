"""A unit's actual size: the changed lines of its pull request as the host
counts them, less generated files. The planner only estimates; this is what
landed, and it is compared with the ceiling without ever blocking a unit."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from statistics import median

from agent_build_kit.config import active
from agent_build_kit.forges import FileChange
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import MERGED


def is_generated(path: str, patterns: Iterable[str]) -> bool:
    """Whether a pattern matches the whole path or just the file's name."""
    name = PurePosixPath(path).name
    return any(fnmatchcase(path, p) or fnmatchcase(name, p) for p in patterns)


def actual_lines(changes: Iterable[FileChange]) -> int:
    """Additions plus deletions over every file that is not generated."""
    patterns = active().generated_file_patterns()
    return sum(
        change.additions + change.deletions
        for change in changes
        if not is_generated(change.path, patterns)
    )


def over_ceiling(lines: int | None) -> bool:
    return lines is not None and lines > active().limits.max_unit_lines


class Kind(Frozen):
    """What units are calibrated by: the repository, the tier and the flag of
    the first flagged group a unit carries (empty when none)."""

    repo: str
    tier: str
    flag: str = ""

    @property
    def label(self) -> str:
        return f"{self.repo} {self.tier}" + (f" [{self.flag}]" if self.flag else "")


class Calibration(Frozen):
    """A kind's ratio and the number of samples behind it."""

    ratio: float
    samples: int


def kind_of(unit: StoredUnit) -> Kind:
    return Kind(repo=unit.repo, tier=unit.tier, flag=unit.flag)


def measured(unit: StoredUnit) -> bool:
    """Whether the unit merged with an estimate and a measured size to compare."""
    return unit.state == MERGED and unit.estimated_lines > 0 and unit.actual_lines is not None


def _merged_at(unit: StoredUnit) -> datetime:
    """When the unit last entered `merged`; the epoch for a record that never says."""
    for entry in reversed(unit.history):
        if entry.get("state") == MERGED:
            try:
                return datetime.fromisoformat(str(entry.get("at", "")))
            except ValueError:
                break
    return datetime.min.replace(tzinfo=UTC)


def _samples(units: Sequence[StoredUnit], kind: Kind) -> list[float]:
    """Actual over the planner's own estimate for the newest merged units of `kind`,
    each clamped to the configured range."""
    limits = active().limits
    low, high = limits.calibration_sample_clamp
    newest = sorted(
        (unit for unit in units if measured(unit) and kind_of(unit) == kind),
        key=_merged_at,
        reverse=True,
    )[: limits.calibration_window]
    return [min(max((unit.actual_lines or 0) / unit.estimated_lines, low), high) for unit in newest]


def sample_count(units: Sequence[StoredUnit], kind: Kind) -> int:
    return len(_samples(units, kind))


def calibration(units: Sequence[StoredUnit], kind: Kind) -> float:
    """What units of `kind` land at, over what the planner estimated: the median of the
    clamped samples, moved toward 1 by how few there are, and kept within 1 and the
    maximum. 1.0 with calibration off or too few samples."""
    limits = active().limits
    samples = _samples(units, kind)
    if not limits.calibrate_estimates or len(samples) < limits.calibration_min:
        return 1.0
    n = len(samples)
    shrunk = 1 + (median(samples) - 1) * n / (n + limits.calibration_shrink)
    return min(max(shrunk, 1.0), limits.calibration_max)


def calibrations(units: Sequence[StoredUnit]) -> dict[Kind, Calibration]:
    """The ratio and sample count of every kind the units hold samples of."""
    kinds = {kind_of(unit) for unit in units if unit.state == MERGED}
    found = {
        kind: Calibration(ratio=calibration(units, kind), samples=sample_count(units, kind))
        for kind in kinds
    }
    return {kind: found[kind] for kind in found if found[kind].samples}


def applied(found: Mapping[Kind, Calibration] | None, kind: Kind) -> Calibration:
    """The calibration to check a unit of `kind` by: none (ratio 1) when calibration
    is off or the kind has no ratio."""
    if not active().limits.calibrate_estimates or not found or kind not in found:
        return Calibration(ratio=1.0, samples=0)
    return found[kind]


def calibrated(lines: int, ratio: float) -> int:
    return round(lines * ratio)
