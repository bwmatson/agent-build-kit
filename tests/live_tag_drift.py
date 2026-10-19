"""What the drift test checks of the live-stack tests: every test that starts an agent carries
exactly one runtime tag, the tag agrees with the runtime the test starts, and an `acp` scenario
with no `claude_code` sibling has a stated reason in its module's table of reasons
(`ACP_ONLY_REASONS`, scenario name to reason; absent is empty). Which tests start an agent is
decided per test from `AGENT_SIGNALS`."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
import tomllib
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS
from tests.runtime_scratch import AGENT_COMMAND, RUNTIMES
from tests.runtime_tag_collection import ROOT
from tests.runtime_tags import PREFIX, runtime_tags

REASONS_TABLE = "ACP_ONLY_REASONS"
INTEGRATION = ROOT / "tests" / "integration"
ACP, CLAUDE_CODE = "runtime_acp", "runtime_claude_code"
SPLITS_HEADING = "This repo's own splits"
UNTAGGED_SPLIT = "rest"
CLAUDE_PROGRAM = "claude"
CLAUDE_ACCOUNT = "claude_account"
PROTOCOL_CLASS = "AcpRuntime"
PROTOCOL_METHODS = {"detect", "list_models", "run"}


class AgentSignals(Frozen):
    """The table of what starts an agent. A call to one of `calls` made through a name imported
    from one of `helper_modules` (dotted names) starts one; so do `AcpRuntime` detection, listing
    or a run, `shutil.which` of an agent program, and a read of the agent command setting. A
    stand-in agent (`install_stand_in`) is not a signal. The helper modules under `tests/` that
    call an agent but are not listed are in `excused_helpers`, each with its reason."""

    helper_modules: tuple[str, ...]
    calls: tuple[str, ...]
    excused_helpers: dict[str, str]


AGENT_SIGNALS = AgentSignals(
    helper_modules=(
        "tests.runtime_scratch",
        "tests.agent_home",
        "tests.scratch_tick",
        "tests.runtimes.policy_agent_harness",
    ),
    calls=("runtime_scratch", "agent_home", "run_tick", "agent_connection", "drive"),
    excused_helpers={},
)


@cache
def parsed(text: str) -> ast.Module:
    return ast.parse(text)


def marks_local_stack(tree: ast.AST) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "local_stack" for n in ast.walk(tree))


def find_live_modules(tests_root: Path) -> list[Path]:
    """Every Python file under `tests_root`, at any depth and whatever its name, whose syntax
    marks a test `local_stack` (`pytestmark`, a decorator, a `pytest.param` mark, a class
    decorator), sorted. A word in a string or comment does not count. Fails, naming the files,
    on one that cannot be parsed."""
    live, broken = [], []
    for path in sorted(tests_root.rglob("*.py")):
        try:
            tree = parsed(path.read_text())
        except SyntaxError:
            broken.append(path)
            continue
        if marks_local_stack(tree):
            live.append(path)
    if broken:
        pytest.fail("cannot parse: " + ", ".join(str(p) for p in broken), pytrace=False)
    return live


def module_of(item: pytest.Item) -> Any:
    parent = item.getparent(pytest.Module)
    assert parent is not None
    return parent.obj


def callee(call: ast.Call) -> tuple[str, str]:
    """The leftmost name and the final name of what a call calls: `a.b.c(...)` is (`a`, `c`)."""
    function = call.func
    last = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
    while isinstance(function, ast.Attribute):
        function = function.value
    return getattr(function, "id", ""), last


def helper_names(tree: ast.Module) -> set[str]:
    """The names a module binds to one of the helper modules, or to a member of one."""
    helpers = set(AGENT_SIGNALS.helper_modules)
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound |= {(a.asname or a.name).split(".")[0] for a in node.names if a.name in helpers}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            bound |= {
                a.asname or a.name
                for a in node.names
                if node.module in helpers or f"{node.module}.{a.name}" in helpers
            }
    return bound


def first_string(call: ast.Call) -> str:
    arg = call.args[0] if call.args else None
    return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else ""


class AgentStart(Frozen):
    """What a test starts: whether an agent, and which of the runtimes."""

    starts: bool = False
    runtimes: frozenset[str] = frozenset()

    def __or__(self, other: AgentStart) -> AgentStart:
        return AgentStart(
            starts=self.starts or other.starts, runtimes=self.runtimes | other.runtimes
        )

    @classmethod
    def of_function(cls, function: ast.AST, tree: ast.Module) -> AgentStart:
        """The signals of one function of the module `tree`."""
        bound = helper_names(tree)
        programs = {agent.program for agent in KNOWN_AGENTS}
        starts, runtimes = False, set()
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and node.id == CLAUDE_ACCOUNT:
                runtimes.add("claude_code")
            if isinstance(node, ast.Name) and node.id == PROTOCOL_CLASS:
                runtimes.add("acp")
            if (isinstance(node, ast.Name) and node.id == "AGENT_COMMAND") or (
                isinstance(node, ast.Constant) and node.value == AGENT_COMMAND
            ):
                starts = True
                runtimes.add("acp")
            if not isinstance(node, ast.Call):
                continue
            root, last = callee(node)
            if root in bound and last in AGENT_SIGNALS.calls:
                starts = True
                if last == "runtime_scratch" and first_string(node) in RUNTIMES:
                    runtimes.add(first_string(node))
            elif last in PROTOCOL_METHODS and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Call) and callee(owner)[1] == PROTOCOL_CLASS:
                    starts = True
                    runtimes.add("acp")
            elif (root, last) == ("shutil", "which"):
                program = first_string(node)
                if program == CLAUDE_PROGRAM:
                    starts = True
                    runtimes.add("claude_code")
                elif program in programs:
                    starts = True
                    runtimes.add("acp")
        return cls(starts=starts, runtimes=frozenset(runtimes))

    @classmethod
    def of(cls, item: pytest.Item) -> AgentStart:
        """What `item` starts: its own function, the fixtures it requests, and the functions of
        their modules they call, and the runtimes in its callspec."""
        total = cls()
        for function, tree in functions_reached(item):
            total |= cls.of_function(function, tree)
        callspec = getattr(item, "callspec", None)
        values = set(callspec.params.values()) if callspec else set()
        return total | cls(runtimes=frozenset(values & set(RUNTIMES)))


def function_tree(function: Any) -> tuple[ast.AST, ast.Module] | None:
    """The syntax of `function` and of the module it is written in."""
    try:
        source = textwrap.dedent(inspect.getsource(function))
        module = Path(inspect.getsourcefile(function) or "").read_text()
    except (OSError, TypeError):
        return None
    return ast.parse(source), parsed(module)


def requested_fixtures(item: pytest.Item) -> dict[str, Any]:
    """The fixtures the test asks for, by its arguments and by those of the fixtures it asks for
    (not the autouse ones), name to definitions: pytest's own are left out and a name with no
    definition maps to an empty tuple."""
    info = getattr(item, "_fixtureinfo", None)
    found: dict[str, Any] = {}
    if info is None:
        return found
    pending = list(info.argnames)
    while pending:
        name = pending.pop()
        if name in found:
            continue
        definitions = info.name2fixturedefs.get(name, ())
        if not definitions:
            found[name] = ()
        elif not definitions[-1].func.__module__.startswith(("_pytest", "pytest")):
            found[name] = definitions[-1:]
            pending += definitions[-1].argnames
    return found


def functions_reached(item: pytest.Item) -> list[tuple[ast.AST, ast.Module]]:
    """The test's function and each requested fixture's, with every function of their modules
    that they call, followed transitively."""
    targets = [getattr(item, "function", None)]
    for definitions in requested_fixtures(item).values():
        targets += [definition.func for definition in definitions]
    reached: list[tuple[ast.AST, ast.Module]] = []
    seen: set[tuple[int, str]] = set()
    pending = [found for target in targets if target and (found := function_tree(target))]
    while pending:
        function, tree = pending.pop()
        reached.append((function, tree))
        defined = {
            n.name: n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called = defined.get(node.func.id)
                if called is not None and (id(tree), called.name) not in seen:
                    seen.add((id(tree), called.name))
                    pending.append((called, tree))
    return reached


def agent_start_notes(items: list[pytest.Item]) -> list[str]:
    """One line per fixture of a test among `items` that could not be resolved and so was not
    counted as starting an agent."""
    return [
        f"{item.nodeid}: fixture {name} cannot be resolved, so it is not counted"
        for item in items
        for name, definitions in requested_fixtures(item).items()
        if not definitions and name != "request"
    ]


def drift(items: list[pytest.Item]) -> list[str]:
    """One message per offence among the collected `items`, each naming the test or the scenario."""
    found: list[str] = []
    scenarios: dict[tuple[Path, str], set[str]] = defaultdict(set)
    tables: dict[Path, dict[str, str]] = {}
    for item in items:
        tags = runtime_tags(item)
        module = module_of(item)
        path = Path(module.__file__)
        tables[path] = getattr(module, REASONS_TABLE, {})
        scenarios[path, getattr(item, "originalname", item.name)].update(tags)
        if len(tags) > 1:
            found.append(f"{item.nodeid}: carries {len(tags)} runtime tags: {', '.join(tags)}")
        elif item.get_closest_marker("local_stack"):
            started = AgentStart.of(item)
            if not tags and started.starts:
                found.append(f"{item.nodeid}: starts an agent and carries no runtime tag")
            elif tags:
                found += [
                    f"{item.nodeid}: tagged {tags[0]} but starts {runtime}"
                    for runtime in sorted(started.runtimes - {tags[0].removeprefix(PREFIX)})
                ]
    for (path, scenario), tags in scenarios.items():
        if ACP in tags and CLAUDE_CODE not in tags and scenario not in tables[path]:
            found.append(
                f"{path.name}::{scenario}: an ACP scenario with no claude_code variant "
                f"and no entry in {REASONS_TABLE}"
            )
    for path, table in tables.items():
        found += [
            f"{path.name}::{scenario}: its entry in {REASONS_TABLE} has an empty reason"
            for scenario, reason in table.items()
            if not reason.strip()
        ]
    return found


def derived_splits(pyproject: Path) -> set[str]:
    """The split names of the `runtime_<name>` markers registered in `pyproject`: `<name>` each."""
    markers = tomllib.loads(pyproject.read_text())["tool"]["pytest"]["ini_options"]["markers"]
    names = (marker.split(":")[0].strip() for marker in markers)
    return {name.removeprefix(PREFIX) for name in names if name.startswith(PREFIX)}


def documented_splits(document: Path) -> set[str]:
    """The split names of the yaml example under "This repo's own splits" in `document`."""
    section = document.read_text().split(SPLITS_HEADING, 1)[1]
    section = re.split(r"^#", section, maxsplit=1, flags=re.MULTILINE)[0]
    example = re.search(r"```yaml\n(.*?)```", section, re.DOTALL)
    assert example, f"no yaml example under {SPLITS_HEADING!r} in {document}"
    return set(yaml.safe_load(example.group(1))["tests"]["e2e_splits"])


def split_name_drift(pyproject: Path, document: Path) -> list[str]:
    """One message per marker with no documented split and per documented split with no marker,
    each naming it."""
    markers, documented = derived_splits(pyproject), documented_splits(document)
    return [
        f"marker {PREFIX}{name} has no split {name} in the example of {document.name}"
        for name in sorted(markers - documented)
    ] + [
        f"split {name} of {document.name} has no registered marker {PREFIX}{name}"
        for name in sorted(documented - markers)
    ]


def split_of(item: pytest.Item) -> str:
    """The split a test is in: the name of its one runtime tag, `rest` when it has none."""
    tags = runtime_tags(item)
    assert len(tags) <= 1, f"{item.nodeid} carries {len(tags)} runtime tags"
    return tags[0].removeprefix(PREFIX) if tags else UNTAGGED_SPLIT


def drifted(pytester: pytest.Pytester, **modules: str) -> list[str]:
    """The drift messages for fixture `modules`, collected the way the project collects its own."""
    pytester.syspathinsert(ROOT)
    pytester.makepyfile(**modules)
    items, _ = pytester.inline_genitems()
    return drift(items)
