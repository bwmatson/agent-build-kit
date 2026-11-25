"""Where a package's unit-test files may sit: one `test_<module>.py` per module, in its mirror
folder, with the files that predate the rule listed in `placement_baseline.toml`.

`uv run python -m tests.placement_baseline --write` rewrites the baseline from the tree.
"""

from collections.abc import Collection, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from tests.tracked_files import ROOT

BASELINE = ROOT / "placement_baseline.toml"


class PlacementTree(Frozen):
    """One tests root: `tests_root` (relative to the repository root) holds the unit tests of
    `modules` (paths under the package's source tree). A root tests folder (`root_tests`) also
    holds other packages' tests, so a file named for one of `other_modules`, and the `docs/`
    folder and the files directly in it that no module claims, are outside the rule."""

    tests_root: Path
    modules: tuple[str, ...]
    other_modules: tuple[str, ...] = ()
    root_tests: bool = False


def offenders(root: Path, tree: PlacementTree) -> list[str]:
    """The `test_*.py` files of `tree` (relative to its tests root, sorted) that are not
    `test_<module>.py` for a module in their mirror folder."""
    raise NotImplementedError


def placement_problems(
    root: Path, trees: Sequence[PlacementTree], baseline: Collection[str]
) -> list[str]:
    """What the files of `trees` get wrong: an offender the baseline does not list, naming the
    module's own test file, and a baseline entry that names no offender."""
    raise NotImplementedError


def read_baseline(path: Path) -> list[str]:
    """The entries of the baseline file at `path`."""
    raise NotImplementedError


def write_baseline(root: Path, trees: Sequence[PlacementTree], path: Path) -> None:
    """Write the offenders of `trees`, sorted, to the baseline file at `path`."""
    raise NotImplementedError


def kit_trees(root: Path) -> list[PlacementTree]:
    """The tests roots of the kit checkout at `root`: the worker, the orchestrator and the core."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """`--write` rewrites the kit's baseline; without it, report the kit's problems."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
