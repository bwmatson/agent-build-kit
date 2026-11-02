"""The guard over agent calls: every call that sends a prompt to an agent records a ledger row.

Found by parsing each module (strings and comments never count):
  - an `AgentRequest(` that sets no `on_result=` and is not the first argument of `recorded(`;
    `on_record=` alone writes transcript events, not a row;
  - a `.run(` on a runtime (`runtimes.active()`, `runtimes.get(...)`, `runtime_for(...)`, or a
    name or attribute called `runtime` or `agent`) in a function that records nothing;
  - a call handed an argv that runs `claude` with `-p` (a list holding `-p` and either
    `"claude"` or a starred command prefix);
  - a `node=` given to `recorded(` or `call_recorder(` that is not an `OverheadNode` or a unit
    graph call node.
`check_sources` returns one message per problem: a site that records nothing and is not on the
allowlist names `path:line`; an allowlist entry whose site now records, or is gone, is reported
as a stale entry. An entry is `(path under the root, function name)` with its reason.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

from agent_build_kit.pipeline.usage_ledger import UNIT_CALL_NODES
from agent_build_kit.pipeline.vocabulary import OverheadNode

SRC_ROOT = Path(__file__).parent.parent / "src" / "agent_build_kit"

# Sites that are allowed to record nothing, each with its reason. Every site records now, so
# it is empty; an entry would need a reason of its own, and may only be removed.
ALLOWLIST: Mapping[tuple[str, str], str] = {}

RECORDERS = frozenset(["recorded", "call_recorder"])
RUNTIME_NAMES = frozenset(["runtime", "agent"])
RUNTIME_FACTORIES = frozenset(["runtime_for", "active"])
NODE_NAMES = frozenset(UNIT_CALL_NODES) | {member.value for member in OverheadNode}


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """The nodes in `scope`, not those of a function defined inside it."""
    stack = list(reversed(list(ast.iter_child_nodes(scope))))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _calls(scope: ast.AST) -> Iterator[ast.Call]:
    return (node for node in _nodes(scope) if isinstance(node, ast.Call))


def _bound_requests(scope: ast.AST) -> dict[int, str]:
    """The name each `x = AgentRequest(...)` binds, by the construction's id."""
    return {
        id(node.value): node.targets[0].id
        for node in _nodes(scope)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and _name(node.value.func) == "AgentRequest"
        and isinstance(node.targets[0], ast.Name)
    }


def _functions(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    yield "", tree
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node.name, node


def _is_runtime(node: ast.expr) -> bool:
    if isinstance(node, ast.BoolOp):
        return any(_is_runtime(value) for value in node.values)
    if isinstance(node, ast.Call):
        func = node.func
        return _name(func) in RUNTIME_FACTORIES or (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and _name(func.value) == "runtimes"
        )
    return _name(node) in RUNTIME_NAMES


def _runs_claude(call: ast.Call) -> bool:
    if not call.args or not isinstance(call.args[0], ast.List):
        return False
    items = call.args[0].elts
    texts = [e.value for e in items if isinstance(e, ast.Constant)]
    return "-p" in texts and ("claude" in texts or any(isinstance(e, ast.Starred) for e in items))


def _scan_function(scope: ast.AST) -> tuple[list[int], list[tuple[int, str]]]:
    """The lines in `scope` that send a prompt and record nothing, and each bad node name."""
    calls = list(_calls(scope))
    helpers = [c for c in calls if _name(c.func) == "recorded" and c.args]
    helped = {id(call.args[0]) for call in helpers}
    # A request built first and handed to `recorded` by its name is recorded as well.
    named = {call.args[0].id for call in helpers if isinstance(call.args[0], ast.Name)}
    bound = _bound_requests(scope)
    requests = [c for c in calls if _name(c.func) == "AgentRequest"]
    bare = [
        c.lineno
        for c in requests
        if bound.get(id(c)) not in named
        and id(c) not in helped
        and not any(k.arg == "on_result" for k in c.keywords)
    ]
    recording = any(_name(c.func) in RECORDERS for c in calls) or any(
        k.arg == "on_result" for c in requests for k in c.keywords
    )
    runs = [
        c.lineno
        for c in calls
        if isinstance(c.func, ast.Attribute)
        and c.func.attr == "run"
        and _is_runtime(c.func.value)
        and not recording
    ]
    claude = [c.lineno for c in calls if _runs_claude(c)]
    nodes = []
    for call in calls:
        if _name(call.func) not in RECORDERS:
            continue
        for keyword in call.keywords:
            if keyword.arg != "node":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value not in NODE_NAMES:
                nodes.append((call.lineno, repr(value.value)))
            elif (
                isinstance(value, ast.Attribute)
                and _name(value.value) == "OverheadNode"
                and value.attr not in OverheadNode.__members__
            ):
                nodes.append((call.lineno, f"OverheadNode.{value.attr}"))
    return sorted({*bare, *runs, *claude}), nodes


def check_sources(root: Path, *, allowlist: Mapping[tuple[str, str], str]) -> list[str]:
    """Every problem under `root`: an agent call that records nothing and is not allowlisted,
    a node name outside the closed sets, and a stale allowlist entry."""
    problems: list[str] = []
    unrecorded: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        for function, scope in _functions(ast.parse(path.read_text())):
            lines, nodes = _scan_function(scope)
            for line, node in nodes:
                problems.append(f"{relative}:{line}: the node {node} is not an OverheadNode")
            if not lines:
                continue
            unrecorded.add((relative, function))
            if (relative, function) not in allowlist:
                problems.append(
                    f"{relative}:{lines[0]}: {function or 'module'} sends a prompt to an agent "
                    "and records no ledger row; build the request through `recorded` or set "
                    "`on_result`"
                )
    for relative, function in sorted(allowlist):
        if (relative, function) not in unrecorded:
            problems.append(
                f"{relative}: the allowlist entry for {function} is stale, its site records "
                "or is gone; remove it"
            )
    return problems
