"""Structural checks on what an agent wrote in the dry-guidance scratch app.

Test code, not framework code: it is specific to the scratch app's language,
Python. Every check is decided by parsing, never by a model's reading.
"""

from __future__ import annotations

import ast
import json
import textwrap
from collections.abc import Iterable
from difflib import SequenceMatcher
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git

# Fixed by the controls in tests/test_dry_checks.py, as measured there: a copy with renamed
# locals and constants scores 1.0, a function that only delegates 0.43 and an unrelated one 0.54.
# So `is_copy` finds statement-for-statement copies only: the same logic inlined into one
# expression scores about 0.54 too and is not found. The count of a case's key literal is the
# backstop for that, which is why every case that asserts no copy also counts its literal.
DUPLICATE_RATIO = 0.8

__all__ = [
    "Definition",
    "DefinitionDiff",
    "calls_by_name",
    "definitions",
    "definitions_in_source",
    "diff_definitions",
    "is_copy",
    "literal_count",
    "prompts_by_session",
    "reaches_by_name",
    "session_prompts",
    "source_at",
]


class Definition(Frozen):
    """A function or method found in a source file."""

    path: str
    name: str
    source: str


class DefinitionDiff(Frozen):
    """The definitions two trees differ by: `added` are absent from the base, `changed` are
    present in both with a different normalised body."""

    added: tuple[Definition, ...]
    changed: tuple[Definition, ...]


def _tokens(node: ast.AST) -> list[str]:
    """The node's kinds in tree order, with names, constants and docstrings reduced to their
    kind; an attribute keeps its name, since `.lower` and `.upper` are different logic."""
    kinds: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            kinds.append(f"Attribute.{child.attr}")
        elif isinstance(child, ast.Constant):
            kinds.append(type(child.value).__name__)
        else:
            kinds.append(type(child).__name__)
    return kinds


def _without_docstring(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
    body = function.body
    first = body[0] if body else None
    is_docstring = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )
    if not is_docstring:
        return function
    return ast.FunctionDef(
        name=function.name,
        args=function.args,
        body=body[1:] or [ast.Pass()],
        decorator_list=[],
        returns=None,
        type_params=[],
    )


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]


def _normalised(source: str) -> list[str]:
    [function] = _functions(ast.parse(textwrap.dedent(source)))[:1]
    return _tokens(_without_docstring(function))[1:]


def definitions_in_source(source: str, path: str = "module.py") -> list[Definition]:
    lines = source.splitlines()
    return [
        Definition(
            path=path,
            name=function.name,
            source=textwrap.dedent("\n".join(lines[function.lineno - 1 : function.end_lineno])),
        )
        for function in _functions(ast.parse(source))
    ]


def is_copy(original: str, candidate: str) -> bool:
    """Whether the candidate function's source repeats the original's logic, after names,
    constants and docstrings are replaced by their kind."""
    ratio = SequenceMatcher(None, _normalised(original), _normalised(candidate), False).ratio()
    return ratio >= DUPLICATE_RATIO


def calls_by_name(source: str, caller: str, callee: str) -> bool:
    """Whether the definition `caller` in `source` calls `callee` as `callee(...)` or
    `x.callee(...)`. A mention in a string or comment is not a call."""
    for function in _functions(ast.parse(source)):
        if function.name != caller:
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if isinstance(target, ast.Name) and target.id == callee:
                return True
            if isinstance(target, ast.Attribute) and target.attr == callee:
                return True
    return False


def reaches_by_name(found: Iterable[Definition], caller: str, callee: str) -> bool:
    """Whether `caller` calls `callee`, directly or through definitions in `found`, resolved by
    name as `calls_by_name` does."""
    calls: dict[str, set[str]] = {}
    for definition in found:
        for node in ast.walk(ast.parse(definition.source)):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
            calls.setdefault(definition.name, set()).add(name)
    seen: set[str] = set()
    pending = [caller]
    while pending:
        name = pending.pop()
        if name == callee and name != caller:
            return True
        if name in seen:
            continue
        seen.add(name)
        pending.extend(calls.get(name, ()))
    return False


def source_at(repo: Path, ref: str, path: str) -> str:
    """The file `path` as `ref` holds it, read from `repo` (bare or not)."""
    return git(repo, "show", f"{ref}:{path}").stdout


def _files(repo: Path, ref: str, under: str) -> list[str]:
    listing = git(repo, "ls-tree", "-r", "--name-only", ref, "--", under).stdout
    return listing.splitlines()


def definitions(repo: Path, ref: str, under: str = "src/") -> list[Definition]:
    """Every definition in the Python files below `under` at `ref`."""
    return [
        found
        for path in _files(repo, ref, under)
        if path.endswith(".py")
        for found in definitions_in_source(source_at(repo, ref, path), path)
    ]


def diff_definitions(repo: Path, base: str, head: str, under: str = "src/") -> DefinitionDiff:
    before = {(d.path, d.name): d for d in definitions(repo, base, under)}
    added: list[Definition] = []
    changed: list[Definition] = []
    for found in definitions(repo, head, under):
        old = before.get((found.path, found.name))
        if old is None:
            added.append(found)
        elif _normalised(old.source) != _normalised(found.source):
            changed.append(found)
    return DefinitionDiff(added=tuple(added), changed=tuple(changed))


def literal_count(repo: Path, ref: str, literal: str, under: str = "src/") -> int:
    """How many times `literal` occurs across the files below `under` at `ref`."""
    return sum(source_at(repo, ref, path).count(literal) for path in _files(repo, ref, under))


def _prompt_requests(record: Path) -> list[tuple[str, str]]:
    """Each `session/prompt` request in a recording, in order: its session and its text."""
    lines = [json.loads(line) for line in record.read_text().splitlines() if line.strip()]
    return [
        (
            str(line["params"].get("sessionId", "")),
            "\n".join(str(block.get("text", "")) for block in line["params"]["prompt"]),
        )
        for line in lines
        if line.get("method") == "session/prompt"
    ]


def session_prompts(record: Path) -> list[str]:
    """The text of each `session/prompt` request in a recording, in the order sent."""
    return [text for _, text in _prompt_requests(record)]


def prompts_by_session(record: Path) -> dict[str, list[str]]:
    """The same prompts, in order, under the session each was sent to."""
    sessions: dict[str, list[str]] = {}
    for session, text in _prompt_requests(record):
        sessions.setdefault(session, []).append(text)
    return sessions
