"""The guard against timing hazards in the test tree.

A hazard is, found by parsing a file (strings and comments never count):
  - "sleep": a call to `time.sleep` or `asyncio.sleep`;
  - "thread": a function that constructs a `threading.Thread` (not a class of the file's
    own) and neither joins it (`.join()` or `.join(<timeout>)`, never a `str.join`) nor
    calls `.set()` in the same function;
  - "port": a call that passes a non-zero integer literal as `port=`, or an address call
    (`bind`, `connect`, `create_server`, `sendto`, or any call named `...Server`) whose
    first argument is a `(host, <non-zero integer literal>)` tuple.
`check_tests` returns one message per problem: a hazard in a file that is neither shared
nor allowlisted names `path:line`; an allowlisted file with no hazard (or none at all) is
reported as a stale allowlist entry naming the file.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).parent

# Files of shared helpers that may hold a hazard, as paths under the tests root.
SHARED_HELPERS: frozenset[str] = frozenset(
    {
        "time_limit.py",
        "waiting.py",
        # The fake servers and stand-ins that run a thread or listen on a port.
        "chat_serving.py",
        "fake_gateway.py",
        "forges/azure_rest_host.py",
        "forges/github_server.py",
        "otlp.py",
        "replay/fake_upstream.py",
        "replay/proxy.py",
        "runtimes/acp_agent.py",
    }
)

# Files with hazards today, as paths under the tests root. It may only shrink: a file
# leaves it when its uses are removed, and nothing is added.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "cli/test_gated_started_units.py",
        "cli/test_round.py",
        "cli/test_tick_host_outage_backoff.py",
        "cli/test_tick_scheduling.py",
        "graph/test_thread_resume.py",
        "integration/test_telemetry_stack.py",
        "pipeline/test_scratch_folder.py",
        "pipeline/test_tier2.py",
        "runtimes/test_acp_outcome.py",
        "serve/test_chat_guards.py",
        "serve/test_serve_binding.py",
        "serve/test_serve_metrics.py",
        "test_telemetry.py",
    }
)


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _nonzero_int(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is int and node.value != 0


# Calls that take an address as `(host, port)` in their first argument: these socket
# calls, and any server class (`HTTPServer`, `ThreadingHTTPServer`, `TCPServer`...).
ADDRESS_CALLS = frozenset(
    {"bind", "connect", "connect_ex", "create_connection", "create_server", "sendto"}
)


def _takes_address(call: ast.Call) -> bool:
    name = _dotted(call.func).rsplit(".", 1)[-1]
    return name in ADDRESS_CALLS or name.endswith("Server")


def _fixed_port(call: ast.Call) -> bool:
    if any(k.arg == "port" and _nonzero_int(k.value) for k in call.keywords):
        return True
    first = call.args[0] if call.args else None
    return (
        _takes_address(call)
        and isinstance(first, ast.Tuple)
        and len(first.elts) == 2
        and _nonzero_int(first.elts[1])
    )


def _sleeps(tree: ast.Module) -> set[str]:
    """Local names that `sleep` was imported as."""
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in ("time", "asyncio")
        for alias in node.names
        if alias.name == "sleep"
    }


def _thread_names(tree: ast.Module) -> set[str]:
    """The dotted names that mean `threading.Thread` in this file: through `import
    threading` (or an alias of it) and `from threading import Thread`. A class of the
    file's own called `Thread` is none of them."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                f"{alias.asname or alias.name}.Thread"
                for alias in node.names
                if alias.name == "threading"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "threading":
            names.update(
                alias.asname or alias.name for alias in node.names if alias.name == "Thread"
            )
    return names


def _numeric(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, int | float)


def _synchronises(call: ast.Call) -> bool:
    """Whether the call is a `Thread.join`/`Event.set` and not a `str.join` or a
    `set.add`-like look-alike: `join` takes nothing or a timeout, `set` takes nothing."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "set":
        return not call.args and not call.keywords
    if func.attr == "join":
        if isinstance(func.value, ast.Constant | ast.JoinedStr):
            return False
        if call.keywords:
            return not call.args and all(k.arg == "timeout" for k in call.keywords)
        return not call.args or (len(call.args) == 1 and _numeric(call.args[0]))
    return False


def _unsynchronised_threads(scope: ast.AST, threads: set[str]) -> list[int]:
    """Lines of `Thread(...)` constructions in a function with no thread `.join(` or
    `.set()`."""
    made: list[int] = []
    synchronised = False
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        if _dotted(node.func) in threads:
            made.append(node.lineno)
        elif _synchronises(node):
            synchronised = True
        # A bound `set` or `join` handed over as the target also signals.
        for argument in [*node.args, *(k.value for k in node.keywords)]:
            if isinstance(argument, ast.Attribute) and argument.attr in ("join", "set"):
                synchronised = True
    return [] if synchronised else made


def _hazards(text: str) -> list[int]:
    """The lines of a file's hazards."""
    tree = ast.parse(text)
    bare = _sleeps(tree)
    threads = _thread_names(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name in ("time.sleep", "asyncio.sleep") or name in bare or _fixed_port(node):
                lines.append(node.lineno)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            lines.extend(_unsynchronised_threads(node, threads))
    # A thread made at module level, outside any function.
    lines.extend(
        line
        for statement in tree.body
        if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        for line in _unsynchronised_threads(statement, threads)
    )
    return sorted(set(lines))


def check_tests(root: Path, *, allowlist: frozenset[str], shared: frozenset[str]) -> list[str]:
    problems: list[str] = []
    hazardous: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix()
        lines = _hazards(path.read_text())
        if not lines:
            continue
        hazardous.add(name)
        if name in shared or name in allowlist:
            continue
        problems.extend(f"{name}:{line}: timing hazard" for line in lines)
    for name in sorted(allowlist - hazardous):
        problems.append(f"{name}: on the allowlist but has no timing hazard; remove it")
    return problems
