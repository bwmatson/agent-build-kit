"""The live tests run their ticks and read a unit's branch through `tests/scratch_tick.py`."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
INTEGRATION = TESTS / "integration"
GRAPH = INTEGRATION / "test_graph_unit.py"
BUILD = INTEGRATION / "test_build_unit.py"
TELEMETRY = INTEGRATION / "test_telemetry_stack.py"
SHARED = TESTS / "scratch_tick.py"


def live_files() -> list[Path]:
    """The three live tests and every other integration test marked `local_stack`."""
    marked = [
        path
        for path in INTEGRATION.glob("test_*.py")
        if re.search(r"\blocal_stack\b", path.read_text())
    ]
    return sorted({GRAPH, BUILD, TELEMETRY, *marked})


def strings_in(node: ast.AST) -> list[str]:
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def calls_named(tree: ast.AST, names: set[str]) -> list[ast.Call]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called in names:
                found.append(node)
    return found


def offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    found = [
        f"{path.name} defines {n.name}"
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "Ticked"
    ]
    found += [
        f"{path.name}:{call.lineno} runs a tick itself"
        for call in calls_named(tree, {"run", "Popen"})
        if "tick" in strings_in(call)
    ]
    found += [
        f"{path.name}:{n.lineno} names commits_on_branch"
        for n in ast.walk(tree)
        if (isinstance(n, ast.Name) and n.id == "commits_on_branch")
        or (isinstance(n, ast.FunctionDef) and n.name == "commits_on_branch")
        or (isinstance(n, ast.Attribute) and n.attr == "commits_on_branch")
    ]
    found += [
        f"{path.name}:{call.lineno} runs git log main.."
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and "log" in strings_in(call)
        and any(text.startswith("main..") for text in strings_in(call))
    ]
    return found


def test_no_live_test_defines_a_tick_result_runs_a_tick_or_reads_a_branch_with_bare_git() -> None:
    found = [offence for path in live_files() for offence in offences(path)]

    assert found == []
    shared = ast.parse(SHARED.read_text())
    assert any(
        text.startswith("main..")
        for call in calls_named(shared, {"git"})
        for text in strings_in(call)
    )


def test_each_of_the_three_files_registers_its_scratch() -> None:
    missing = []
    for path in (GRAPH, BUILD, TELEMETRY):
        tree = ast.parse(path.read_text())
        registers = bool(calls_named(tree, {"register_scratch"}))
        fixture = any(
            isinstance(n, ast.FunctionDef) and n.name == "scratch" for n in ast.walk(tree)
        )
        # The telemetry helper builds its scratch inside the test, so no fixture argument
        # can carry it to the dump.
        if not (registers or (fixture and path != TELEMETRY)):
            missing.append(path.name)

    assert missing == []


def test_each_live_test_that_runs_a_tick_ends_it_through_the_guarded_branch_check() -> None:
    bypassing = []
    for path in live_files():
        tree = ast.parse(path.read_text())
        if calls_named(tree, {"run_tick"}) and not calls_named(tree, {"commits_on_unit_branch"}):
            bypassing.append(path.name)

    assert bypassing == []


def test_a_copy_of_the_graph_test_with_a_tick_that_builds_nothing_fails_with_hints_first(
    pytester: pytest.Pytester,
) -> None:
    source = re.sub(r"pytest\.mark\.skipif\([^\n]*\),?\n", "", GRAPH.read_text())
    pytester.makepyfile(test_graph_copy=source)
    pytester.makeconftest(
        "import stat\n"
        "import sys\n"
        "\n"
        "import pytest\n"
        "\n"
        "from tests import scratch_tick\n"
        "\n"
        "\n"
        "@pytest.fixture(autouse=True)\n"
        "def stand_in_abk(tmp_path_factory, monkeypatch):\n"
        '    program = tmp_path_factory.mktemp("stand-in") / "abk"\n'
        "    program.write_text(f\"#!{sys.executable}\\nprint('nothing ready to build')\\n\")\n"
        "    program.chmod(program.stat().st_mode | stat.S_IXUSR)\n"
        '    monkeypatch.setattr(scratch_tick, "ABK", program)\n'
    )
    pytester.makeini("[pytest]\nmarkers =\n    local_stack: a live test\n")

    result = pytester.runpytest_inprocess("-p", "tests.scratch_dump", "-p", "no:cacheprovider")

    assert result.ret != 0
    messages = [line for line in result.outlines if line.startswith("E ")]
    assert messages and "Failed: cause hints:" in messages[0], result.outlines
    assert any("nothing ready to build" in line for line in messages)
