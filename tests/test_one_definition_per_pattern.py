"""No two modules under src/ each compile the same pattern at module level: the
pattern is defined once and imported by the rest."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

from tests.time_limit import LOADED_TEST_TIME_LIMIT

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "agent_build_kit"


def compiled(tree: ast.Module) -> list[tuple[int, str]]:
    """Each module-level `NAME = re.compile(<literal>[, flags])` as its line and its key."""
    found = []
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign) or node.value is None:
            continue
        call = node.value
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "compile"
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "re"
            and call.args
        ):
            continue
        try:
            pattern = ast.literal_eval(call.args[0])
        except ValueError:
            continue
        flags = [
            ast.unparse(extra) for extra in [*call.args[1:], *(k.value for k in call.keywords)]
        ]
        found.append((node.lineno, f"{pattern!r} flags={flags}"))
    return found


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_no_pattern_is_compiled_at_module_level_in_two_modules() -> None:
    sites: dict[str, list[str]] = defaultdict(list)
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        name = path.relative_to(SOURCE_ROOT).as_posix()
        for line, key in compiled(ast.parse(path.read_text())):
            sites[key].append(f"{name}:{line}")

    problems = [f"{key}: {', '.join(where)}" for key, where in sites.items() if len(where) > 1]

    assert not problems, "define each pattern once and import it:\n" + "\n".join(problems)
