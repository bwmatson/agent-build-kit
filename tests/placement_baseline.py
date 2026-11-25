"""Where a package's unit-test files may sit: one `test_<module>.py` per module, in its mirror
folder, with the files that predate the rule listed in `placement_baseline.toml`.

`uv run python -m tests.placement_baseline --write` rewrites the baseline from the tree. The
baseline may only shrink: once a file is moved into its module's test file, its entry goes.
"""

import json
import sys
import tomllib
from collections.abc import Collection, Sequence
from pathlib import Path, PurePosixPath

from agent_build_kit.model import Frozen
from tests.tracked_files import ROOT, tracked
from tests.workspace_packages import PACKAGES, source_root

BASELINE = ROOT / "placement_baseline.toml"
OUTSIDE_FOLDERS = frozenset({"integration", "e2e"})


class PlacementTree(Frozen):
    """One tests root: `tests_root` (relative to the repository root) holds the unit tests of
    `modules` (paths under the package's source tree). A root tests folder (`root_tests`) also
    holds other packages' tests, so a file named for one of `other_modules`, and the `docs/`
    folder and the files directly in it that no module claims, are outside the rule."""

    tests_root: Path
    modules: tuple[str, ...]
    other_modules: tuple[str, ...] = ()
    root_tests: bool = False


def _stem(module: str) -> str:
    return PurePosixPath(module).stem


def _folder(module: str) -> str:
    return PurePosixPath(module).parent.as_posix()


def _claimants(relative: PurePosixPath, modules: Collection[str]) -> list[str]:
    """The modules of the file's mirror folder whose `test_<module>` its name begins with, the
    longest name last."""
    found = [
        module
        for module in modules
        if _stem(module) != "__init__"
        and _folder(module) == relative.parent.as_posix()
        and relative.name.startswith(f"test_{_stem(module)}")
    ]
    return sorted(found, key=lambda module: len(_stem(module)))


def _is_offender(relative: PurePosixPath, tree: PlacementTree) -> bool:
    if OUTSIDE_FOLDERS.intersection(relative.parts[:-1]):
        return False
    own = _claimants(relative, tree.modules)
    if any(relative.name == f"test_{_stem(module)}.py" for module in own):
        return False
    if tree.root_tests:
        if _claimants(relative, tree.other_modules):
            return False
        if relative.parts[0] == "docs" or (len(relative.parts) == 1 and not own):
            return False
    return True


def offenders(root: Path, tree: PlacementTree) -> list[str]:
    """The `test_*.py` files of `tree` (relative to its tests root, sorted) that are not
    `test_<module>.py` for a module in their mirror folder."""
    found = []
    for path in tracked(root):
        if not path.is_relative_to(tree.tests_root):
            continue
        relative = PurePosixPath(path.relative_to(tree.tests_root).as_posix())
        if (
            relative.name.startswith("test_")
            and relative.suffix == ".py"
            and _is_offender(relative, tree)
        ):
            found.append(relative.as_posix())
    return sorted(found)


def _belongs_in(relative: str, tree: PlacementTree) -> str:
    claimants = _claimants(PurePosixPath(relative), tree.modules)
    if not claimants:
        return "no module of its folder"
    return f"{_folder(claimants[-1])}/test_{_stem(claimants[-1])}.py"


def placement_problems(
    root: Path, trees: Sequence[PlacementTree], baseline: Collection[str]
) -> list[str]:
    """What the files of `trees` get wrong: an offender the baseline does not list, naming the
    module's own test file, and a baseline entry that names no offender."""
    problems: list[str] = []
    seen: set[str] = set()
    for tree in trees:
        for relative in offenders(root, tree):
            seen.add(relative)
            if relative not in baseline:
                problems.append(
                    f"{tree.tests_root / relative} is not the test file of a module: add its "
                    f"cases to {_belongs_in(relative, tree)}"
                )
    problems += [
        f"baseline entry {entry} names no offending file: remove it from the baseline"
        for entry in baseline
        if entry not in seen
    ]
    return problems


def read_baseline(path: Path) -> list[str]:
    """The entries of the baseline file at `path`."""
    return list(tomllib.loads(path.read_text())["files"])


def write_baseline(root: Path, trees: Sequence[PlacementTree], path: Path) -> None:
    """Write the offenders of `trees`, sorted, to the baseline file at `path`."""
    entries = sorted({name for tree in trees for name in offenders(root, tree)})
    lines = [f"  {json.dumps(name)}," for name in entries]
    path.write_text("\n".join(["files = [", *lines, "]", ""]))


def _modules(root: Path, project: Path) -> tuple[str, ...]:
    source = source_root(project).relative_to(root)
    return tuple(
        sorted(
            path.relative_to(source).as_posix()
            for path in tracked(root)
            if path.is_relative_to(source) and path.suffix == ".py"
        )
    )


def kit_trees(root: Path) -> list[PlacementTree]:
    """The tests roots of the kit checkout at `root`: the worker, the orchestrator and the core
    (the root `tests/` until the core's own folder holds its tests)."""
    core = tuple(
        sorted(
            {
                *_modules(root, PACKAGES.get("root", root)),
                *_modules(root, PACKAGES.get("core", root / "packages" / "core")),
            }
        )
    )
    worker = _modules(root, PACKAGES.get("worker", root / "packages" / "worker"))
    orchestrator = _modules(root, PACKAGES.get("orchestrator", root / "packages" / "orchestrator"))
    others = (*worker, *orchestrator)
    return [
        PlacementTree(
            tests_root=Path("tests"), modules=core, other_modules=others, root_tests=True
        ),
        PlacementTree(tests_root=Path("packages") / "core" / "tests", modules=core),
        PlacementTree(tests_root=Path("packages") / "worker" / "tests", modules=worker),
        PlacementTree(tests_root=Path("packages") / "orchestrator" / "tests", modules=orchestrator),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """`--write` rewrites the kit's baseline; without it, report the kit's problems."""
    args = list(sys.argv[1:] if argv is None else argv)
    trees = kit_trees(ROOT)
    if "--write" in args:
        write_baseline(ROOT, trees, BASELINE)
        return 0
    problems = placement_problems(ROOT, trees, read_baseline(BASELINE))
    print("\n".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
