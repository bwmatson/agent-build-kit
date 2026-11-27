"""The Python reader of a project's code map.

It reads each source file with `ast`, takes signatures from the source text, and resolves
imports, calls and bases only when they land on exactly one file of the project."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath

from agent_build_kit.codemap.graph import Edge, FileFacts, Reading, Symbol

MAX_DEFAULT = 40
MAX_SIGNATURE = 200
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPES = (*_FUNCTIONS, ast.ClassDef)
_TEST_FOLDERS = ("tests", "test")

Ref = tuple[str, str]  # (file, top-level name)


def _first_doc_line(node: ast.AST) -> str:
    doc = ast.get_docstring(node) if isinstance(node, (*_SCOPES, ast.Module)) else None
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _dotted(expr: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(expr, ast.Attribute):
        parts.append(expr.attr)
        expr = expr.value
    if not isinstance(expr, ast.Name):
        return None
    parts.append(expr.id)
    return ".".join(reversed(parts))


def _module_names(path: str) -> list[str]:
    """The dotted names a file is indexed under: from the root and below each `src` folder."""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    names = [".".join(parts)] if parts else []
    for i, part in enumerate(parts[:-1]):
        if part == "src":
            names.append(".".join(parts[i + 1 :]))
    return names


class _Source:
    """One parsed file: its text, line offsets and tree."""

    def __init__(self, path: str, text: str, tree: ast.Module) -> None:
        self.path = path
        self.text = text
        self.tree = tree
        self.starts = [m.start() for m in re.finditer(r"[^\n]*\n|[^\n]+", text)] or [0]

    def offset(self, line: int, col: int) -> int:
        """The character offset of an `ast` position, whose column counts UTF-8 bytes."""
        start = self.starts[line - 1]
        row = self.text[start:].split("\n", 1)[0]
        return start + len(row.encode("utf-8")[:col].decode("utf-8", errors="ignore"))

    def header_end(self, begin: int, first_line: int) -> int:
        """Where the declaration's header ends: its first colon outside any bracket."""
        depth = 0
        stream = io.StringIO(self.text[begin:]).readline
        try:
            for token in tokenize.generate_tokens(stream):
                if token.type != tokenize.OP:
                    continue
                if token.string in "([{":
                    depth += 1
                elif token.string in ")]}":
                    depth -= 1
                elif token.string == ":" and depth == 0:
                    row, col = token.start
                    return begin + col if row == 1 else self.starts[first_line + row - 2] + col
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        return begin + len(self.text[begin:].split("\n", 1)[0])

    def signature(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        begin = self.offset(node.lineno, node.col_offset)
        text = self.text[begin : self.header_end(begin, node.lineno)]
        if isinstance(node, _FUNCTIONS):
            defaults = [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]
            cuts = []
            for default in defaults:
                if default.end_lineno is None or default.end_col_offset is None:
                    continue
                low = self.offset(default.lineno, default.col_offset)
                high = self.offset(default.end_lineno, default.end_col_offset)
                if len(" ".join(self.text[low:high].split())) > MAX_DEFAULT:
                    cuts.append((low - begin, high - begin))
            for low, high in sorted(cuts, reverse=True):
                text = text[:low] + "..." + text[high:]
        text = " ".join(text.split())
        if len(text) > MAX_SIGNATURE:
            text = text[: MAX_SIGNATURE - 1] + "…"
        return text


def _symbols_of(source: _Source) -> list[tuple[Symbol, ast.AST, str | None]]:
    """Top-level classes and functions and the methods of those classes, in source order.

    Each is (symbol, node, owning class's symbol name); a name defined twice gets `#2`."""
    found: list[tuple[Symbol, ast.AST, str | None]] = []
    seen: dict[str, int] = {}

    def add(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, prefix: str) -> str:
        base = f"{prefix}{node.name}"
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base}#{seen[base]}"
        first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        last = node.end_lineno or node.lineno
        symbol = Symbol(
            kind="class" if isinstance(node, ast.ClassDef) else "function",
            name=name,
            span=(first, last),
            lines=last - first + 1,
            signature=source.signature(node),
            doc=_first_doc_line(node),
        )
        found.append((symbol, node, prefix[:-1] if prefix else None))
        return name

    for node in source.tree.body:
        if not isinstance(node, _SCOPES):
            continue
        name = add(node, "")
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, _FUNCTIONS):
                    add(child, f"{name}.")
    return found


class _Project:
    """What the reader knows of every source file while it resolves names."""

    def __init__(self, paths: Sequence[str], sources: dict[str, _Source]) -> None:
        self.sources = sources
        self.index: dict[str, set[str]] = {}
        for path in paths:
            for name in _module_names(path):
                self.index.setdefault(name, set()).add(path)
        # each file's first top-level definitions, and each class's first methods
        self.top: dict[str, dict[str, str]] = {}
        self.methods: dict[Ref, set[str]] = {}
        self.bases: dict[Ref, list[ast.expr]] = {}
        self.symbols: dict[str, list[tuple[Symbol, ast.AST, str | None]]] = {}
        for path, source in sources.items():
            self.symbols[path] = _symbols_of(source)
            top = self.top.setdefault(path, {})
            for symbol, node, owner in self.symbols[path]:
                if "#" in symbol.name:
                    continue
                if owner is None:
                    top[symbol.name] = symbol.kind
                    if isinstance(node, ast.ClassDef):
                        self.bases[(path, symbol.name)] = list(node.bases)
                else:
                    self.methods.setdefault((path, owner), set()).add(symbol.name.split(".")[-1])
        self.module_bindings: dict[str, dict[str, str]] = {}
        self.symbol_bindings: dict[str, dict[str, Ref]] = {}
        self.imports: set[tuple[str, str]] = set()
        for path, source in sources.items():
            self._read_imports(path, source.tree)

    def resolve_module(self, name: str) -> str | None:
        found = self.index.get(name, set())
        return next(iter(found)) if len(found) == 1 else None

    def _read_imports(self, path: str, tree: ast.Module) -> None:
        modules = self.module_bindings.setdefault(path, {})
        symbols = self.symbol_bindings.setdefault(path, {})

        def link(target: str | None) -> None:
            if target is not None and target != path:
                self.imports.add((path, target))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = self.resolve_module(alias.name)
                    link(target)
                    if target is not None:
                        modules[alias.asname or alias.name] = target
            elif isinstance(node, ast.ImportFrom):
                base = self._absolute(path, node)
                if base is None:
                    continue
                module = self.resolve_module(base)
                for alias in node.names:
                    if alias.name == "*":
                        link(module)
                        continue
                    sub = self.resolve_module(f"{base}.{alias.name}" if base else alias.name)
                    bound = alias.asname or alias.name
                    if sub is not None:
                        link(sub)
                        modules[bound] = sub
                    elif module is not None:
                        link(module)
                        symbols[bound] = (module, alias.name)

    @staticmethod
    def _absolute(path: str, node: ast.ImportFrom) -> str | None:
        """The dotted module an import-from names, a relative one taken from the file's package."""
        if not node.level:
            return node.module or ""
        package = list(PurePosixPath(path).parent.parts)
        if node.level - 1 > len(package):
            return None
        package = package[: len(package) - (node.level - 1)]
        return ".".join([*package, *(node.module.split(".") if node.module else [])])

    def symbol(self, path: str, dotted: str) -> Ref | None:
        """The top-level function or class a dotted name written in `path` stands for."""
        *prefix, name = dotted.split(".")
        if not prefix:
            if name in self.top.get(path, {}):
                return (path, name)
            target = self.symbol_bindings.get(path, {}).get(name)
            return target if target and target[1] in self.top.get(target[0], {}) else None
        module = self.module_bindings.get(path, {}).get(".".join(prefix))
        if module is not None and name in self.top.get(module, {}):
            return (module, name)
        return None

    def class_of(self, path: str, dotted: str) -> Ref | None:
        found = self.symbol(path, dotted)
        return found if found and self.top[found[0]][found[1]] == "class" else None

    def method(self, cls: Ref, name: str, seen: set[Ref] | None = None) -> str | None:
        """The id of method `name` on the class or, depth first, its project bases."""
        seen = seen if seen is not None else set()
        if cls in seen:
            return None
        seen.add(cls)
        if name in self.methods.get(cls, set()):
            return f"{cls[0]}::{cls[1]}.{name}"
        for base in self.bases.get(cls, []):
            dotted = _dotted(base)
            resolved = self.class_of(cls[0], dotted) if dotted else None
            found = self.method(resolved, name, seen) if resolved else None
            if found:
                return found
        return None


def _test_folder_parts(path: str) -> list[str] | None:
    parts = list(PurePosixPath(path).parent.parts)
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] in _TEST_FOLDERS:
            return parts[i + 1 :]
    return None


def _module_folder_parts(path: str, paths: Sequence[str]) -> list[str]:
    parts = list(PurePosixPath(path).parent.parts)
    if "src" in parts:
        return parts[parts.index("src") + 2 :]
    for i in range(len(parts)):
        if "/".join([*parts[: i + 1], "__init__.py"]) in paths:
            return parts[i + 1 :]
    return parts


def _tests_of(path: str, paths: Sequence[str], tests: Sequence[str]) -> tuple[str, ...]:
    name = PurePosixPath(path).name
    if name == "__init__.py":
        return ()
    wanted = f"test_{name}"
    folder = _module_folder_parts(path, paths)
    return tuple(
        sorted(
            test
            for test in tests
            if PurePosixPath(test).name == wanted and _test_folder_parts(test) == folder
        )
    )


def _walk(nodes: Sequence[ast.AST]) -> Iterator[ast.AST]:
    for node in nodes:
        yield from ast.walk(node)


def _parameters(nodes: Sequence[ast.AST]) -> set[str]:
    return {a.arg for n in _walk(nodes) if isinstance(n, ast.arguments) for a in _all_args(n)}


def _all_args(arguments: ast.arguments) -> list[ast.arg]:
    found = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    return [*found, *(a for a in (arguments.vararg, arguments.kwarg) if a)]


class PythonReader:
    suffixes: tuple[str, ...] = (".py",)

    def read(self, root: Path, sources: Sequence[str], tests: Sequence[str]) -> Reading:
        parsed: dict[str, _Source] = {}
        lines: dict[str, int] = {}
        problems: list[str] = []
        for path in sources:
            try:
                text = (root / path).read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                problems.append(f"{path}: {error}")
                continue
            lines[path] = len(text.splitlines())
            try:
                parsed[path] = _Source(path, text, ast.parse(text))
            except (SyntaxError, ValueError) as error:
                problems.append(f"{path}: does not parse: {error}")
        project = _Project(sources, parsed)

        edges = {Edge(kind="imports", source=a, target=b) for a, b in project.imports}
        files = []
        for path in lines:
            facts_symbols: tuple[Symbol, ...] = ()
            doc = ""
            if path in parsed:
                doc = _first_doc_line(parsed[path].tree)
                facts_symbols = tuple(s for s, _, _ in project.symbols[path])
                edges |= self._edges(project, path)
            files.append(
                FileFacts(
                    path=path,
                    lines=lines[path],
                    doc=doc,
                    symbols=facts_symbols,
                    tests=_tests_of(path, sources, tests),
                )
            )
        return Reading(files=tuple(files), edges=tuple(edges), problems=tuple(problems))

    @staticmethod
    def _edges(project: _Project, path: str) -> set[Edge]:
        tree = project.sources[path].tree
        edges: set[Edge] = set()

        def invoke(source: str, scope: Sequence[ast.AST], cls: Ref | None) -> None:
            shadowed = _parameters(scope)
            for node in _walk(scope):
                if not isinstance(node, ast.Call):
                    continue
                target = PythonReader._target(project, path, node.func, cls, shadowed)
                if target:
                    edges.add(Edge(kind="invokes", source=source, target=target))

        module_level = [n for n in tree.body if not isinstance(n, _SCOPES)]
        invoke(path, module_level, None)
        for symbol, node, owner in project.symbols[path]:
            cls_name = owner or (symbol.name if symbol.kind == "class" else None)
            cls = (path, cls_name) if cls_name else None
            node_id = f"{path}::{symbol.name}"
            if isinstance(node, ast.ClassDef):
                invoke(node_id, [n for n in node.body if not isinstance(n, _FUNCTIONS)], cls)
                for base in node.bases:
                    dotted = _dotted(base)
                    resolved = project.class_of(path, dotted) if dotted else None
                    if resolved and "#" not in symbol.name:
                        target = f"{resolved[0]}::{resolved[1]}"
                        edges.add(Edge(kind="inherits", source=node_id, target=target))
            elif isinstance(node, _FUNCTIONS):
                invoke(node_id, node.body, cls)
        return edges

    @staticmethod
    def _target(
        project: _Project, path: str, func: ast.expr, cls: Ref | None, shadowed: set[str]
    ) -> str | None:
        dotted = _dotted(func)
        if dotted is None or dotted.split(".")[0] in shadowed:
            return None
        parts = dotted.split(".")
        if parts[0] in ("self", "cls") and len(parts) == 2:
            return project.method(cls, parts[1]) if cls else None
        resolved = project.symbol(path, dotted)
        if resolved:
            return f"{resolved[0]}::{resolved[1]}"
        if len(parts) >= 2:
            owner = project.class_of(path, ".".join(parts[:-1]))
            if owner:
                return project.method(owner, parts[-1])
        return None
