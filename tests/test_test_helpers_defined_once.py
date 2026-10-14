"""The guard against a test helper being copied from file to file (spec: dry-cleanup).

The helpers merged into the shared test modules are defined there and nowhere else, no test
file repeats the body of a shared helper under any name, and the listed names (`commit`,
`write_change`) are not copied with the same body. A same-named helper with a different body
(`commit`, `inst`, `runner`) is a different helper and is allowed.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SHARED = {"factories.py", "conftest.py"}
# Names that stand for one helper, so a definition outside the shared modules is a copy.
MERGED = ("fake_openspec", "make_installation", "commit_files", "commit_unit_work")
# Names several files use for different helpers, so only an identical body is a copy.
COPIED = ("commit", "write_change")


def helpers() -> list[tuple[str, Path, str]]:
    """Each top-level function of a test module that is not a test, as (name, file, shape)."""
    found = []
    for path in sorted(TESTS.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if (
                not isinstance(node, ast.FunctionDef)
                or node.decorator_list
                or node.name.startswith("test_")
            ):
                continue
            body = node.body[1:] if ast.get_docstring(node) else node.body
            shape = ast.dump(ast.Module(body=body, type_ignores=[])) + ast.dump(node.args)
            found.append((node.name, path, shape))
    return found


def test_each_merged_helper_is_defined_only_in_a_shared_module() -> None:
    where = defaultdict(list)
    for name, path, _ in helpers():
        if name in MERGED:
            where[name].append(path.name)

    problems = {
        name: where[name]
        for name in MERGED
        if not where[name] or any(file not in SHARED for file in where[name])
    }

    assert not problems, f"each must be defined in {sorted(SHARED)} only: {problems}"


def test_the_shared_commit_helper_is_not_copied_into_a_test_file() -> None:
    commits = [(path, shape) for name, path, shape in helpers() if name == "commit"]
    shared = {shape for path, shape in commits if path.name in SHARED}

    copies = [path.name for path, shape in commits if path.name not in SHARED and shape in shared]
    restack = [path.name for path, _ in commits if path.name.startswith("test_restack")]

    assert shared, "the shared `commit` is defined in tests/factories.py"
    assert not copies, f"copies of the shared commit helper: {copies}"
    assert not restack, f"the restack tests import the shared commit: {restack}"


def test_no_two_merged_helpers_share_a_name_and_a_body() -> None:
    seen = defaultdict(list)
    for name, path, shape in helpers():
        if name in (*MERGED, *COPIED):
            seen[name, shape].append(str(path.relative_to(TESTS)))

    duplicated = {name: files for (name, _), files in seen.items() if len(files) > 1}

    assert not duplicated, f"define once in a shared module and import: {duplicated}"


def test_no_test_file_repeats_the_body_of_a_shared_helper_under_any_name() -> None:
    found = helpers()
    shared = {shape: name for name, path, shape in found if path.name in SHARED}

    copies = {
        f"{path.relative_to(TESTS)}:{name}": shared[shape]
        for name, path, shape in found
        if path.name not in SHARED and shape in shared
    }

    assert not copies, f"import the shared helper instead of copying it: {copies}"
