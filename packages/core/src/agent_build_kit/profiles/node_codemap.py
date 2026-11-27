"""The node profile's code reader: TypeScript and JavaScript projects read with tree-sitter."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Callable, Sequence
from pathlib import Path

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from agent_build_kit.codemap.graph import Edge, FileFacts, Reading, Symbol

# The node profile's one list of source extensions, and the one rule for a test file's name.
SOURCE = ("ts", "tsx", "js", "jsx", "mts")
SUFFIXES = tuple(f".{ext}" for ext in SOURCE)
TEST_FILE = re.compile(rf"\.(test|spec)\.({'|'.join(SOURCE)})$")
_TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
_TSX = Language(tree_sitter_typescript.language_tsx())
_MAX_DEFAULT = 40
_MAX_SIGNATURE = 200
_FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "function"})
_CLASSES = frozenset({"class_declaration", "abstract_class_declaration", "class"})


def parser_for(path: str) -> Parser:
    """A parser of the TSX grammar for the extensions that may hold JSX (`.tsx`, `.jsx`, and
    `.js`, which Vite projects sometimes keep JSX in), else of the TypeScript one."""
    return Parser(_TSX if path.endswith(("x", ".js")) else _TYPESCRIPT)


def node_text(node: Node | None) -> str:
    return node.text.decode(errors="replace") if node is not None and node.text else ""


_text = node_text


class _Def:
    """A top-level symbol: its node id's name, the node that owns its calls, its facts."""

    def __init__(self, symbol: Symbol, owner: Node, heritage: Node | None = None) -> None:
        self.symbol = symbol
        self.owner = owner
        self.heritage = heritage


def _signature(source: bytes, start: Node, body: Node | None) -> str:
    end = body.start_byte if body is not None else start.end_byte
    pieces: list[tuple[int, int, str]] = []
    stack = [start]
    while stack:
        node = stack.pop()
        if node.start_byte >= end:
            continue
        if node.type == "formal_parameters":
            for child in node.named_children:
                value = child.child_by_field_name("value")
                if value is not None and value.end_byte - value.start_byte > _MAX_DEFAULT:
                    pieces.append((value.start_byte, value.end_byte, "..."))
            continue
        stack.extend(node.children)
    text, at = "", start.start_byte
    for first, last, replacement in sorted(pieces):
        text += source[at:first].decode(errors="replace") + replacement
        at = last
    text += source[at:end].decode(errors="replace")
    text = " ".join(text.split())
    text = text.removesuffix("{").removesuffix(":").rstrip()
    return text if len(text) <= _MAX_SIGNATURE else text[: _MAX_SIGNATURE - 1] + "…"


def _doc(node: Node) -> str:
    comment = node.prev_sibling
    if comment is None or comment.type != "comment" or not _text(comment).startswith("/**"):
        return ""
    for line in _text(comment).removeprefix("/**").removesuffix("*/").splitlines():
        stripped = line.strip().lstrip("*").strip()
        if stripped:
            return stripped
    return ""


def _symbol(source: bytes, kind: str, name: str, outer: Node, start: Node, body: Node | None):
    first, last = outer.start_point.row + 1, outer.end_point.row + 1
    return Symbol(
        kind=kind,
        name=name,
        span=(first, last),
        lines=last - first + 1,
        signature=_signature(source, start, body),
        doc=_doc(outer),
    )


def _definitions(source: bytes, root: Node) -> list[_Def]:
    found: list[_Def] = []
    for statement in root.named_children:
        outer = statement
        node = statement
        if statement.type == "export_statement":
            node = statement.child_by_field_name("declaration") or statement.child_by_field_name(
                "value"
            )
            if node is None:
                continue
        if node.type in {"function_declaration", "generator_function_declaration"}:
            name = _text(node.child_by_field_name("name"))
            symbol = _symbol(
                source, "function", name, outer, node, node.child_by_field_name("body")
            )
            found.append(_Def(symbol, node))
        elif node.type in _FUNCTION_VALUES | {"generator_function"}:
            body = node.child_by_field_name("body")
            name = _text(node.child_by_field_name("name")) or "default"
            found.append(_Def(_symbol(source, "function", name, outer, node, body), node))
        elif node.type in _CLASSES:
            name = _text(node.child_by_field_name("name")) or "default"
            body = node.child_by_field_name("body")
            symbol = _symbol(source, "class", name, outer, node, body)
            found.append(_Def(symbol, node, heritage=node))
            if body is None:
                continue
            for member in body.named_children:
                if member.type != "method_definition":
                    continue
                method = f"{name}.{_text(member.child_by_field_name('name'))}"
                mbody = member.child_by_field_name("body")
                found.append(
                    _Def(_symbol(source, "function", method, member, member, mbody), member)
                )
        elif node.type in {"lexical_declaration", "variable_declaration"} and (
            len(node.named_children) == 1
        ):
            declarator = node.named_children[0]
            value = declarator.child_by_field_name("value")
            if declarator.type == "variable_declarator" and (
                value is not None and value.type in _FUNCTION_VALUES
            ):
                name = _text(declarator.child_by_field_name("name"))
                body = value.child_by_field_name("body")
                found.append(_Def(_symbol(source, "function", name, outer, node, body), value))
    return found


def _literal(node: Node | None) -> str | None:
    if node is None or node.type != "string":
        return None
    return _text(node)[1:-1]


def _module_specifiers(root: Node) -> list[str]:
    found: list[str] = []
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(reversed(node.children))
        if node.type in {"import_statement", "export_statement"}:
            specifier = _literal(node.child_by_field_name("source"))
            if specifier is not None:
                found.append(specifier)
        elif node.type == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            is_load = function is not None and (
                function.type == "import" or _text(function) == "require"
            )
            if is_load and arguments is not None and arguments.named_children:
                specifier = _literal(arguments.named_children[0])
                if specifier is not None:
                    found.append(specifier)
    return found


def _bindings(root: Node) -> list[tuple[str, str, str]]:
    """(local name, specifier, imported name) for each import; `*` is a namespace."""
    found: list[tuple[str, str, str]] = []
    for statement in root.named_children:
        if statement.type != "import_statement":
            continue
        specifier = _literal(statement.child_by_field_name("source"))
        if specifier is None:
            continue
        for clause in statement.named_children:
            if clause.type != "import_clause":
                continue
            for part in clause.named_children:
                if part.type == "identifier":
                    found.append((_text(part), specifier, "default"))
                elif part.type == "namespace_import":
                    found.append((_text(part.named_children[0]), specifier, "*"))
                elif part.type == "named_imports":
                    for item in part.named_children:
                        name = item.child_by_field_name("name")
                        alias = item.child_by_field_name("alias") or name
                        found.append((_text(alias), specifier, _text(name)))
    return found


def _candidates(base: str) -> list[str]:
    options = [base]
    options += [base + suffix for suffix in SUFFIXES]
    options += [f"{base}/index{suffix}" for suffix in SUFFIXES]
    if base.endswith(".js"):
        options += [base[:-3] + suffix for suffix in SUFFIXES]
    return options


def _tested_stem(path: str) -> str | None:
    """The module stem a test file's name points at, or None when it is not a test file name."""
    name = posixpath.basename(path)
    match = TEST_FILE.search(name)
    return name[: match.start()] if match else None


def _tests_of(source: str, tests: Sequence[str]) -> list[str]:
    stem = posixpath.splitext(posixpath.basename(source))[0]
    folder = posixpath.dirname(source)
    parts = folder.split("/") if folder else []
    below = parts[parts.index("src") + 1 :] if "src" in parts else parts
    matched: list[str] = []
    for test in tests:
        if _tested_stem(test) != stem:
            continue
        where = posixpath.dirname(test)
        if where == folder or where == posixpath.join(folder, "__tests__"):
            matched.append(test)
            continue
        where_parts = where.split("/") if where else []
        roots = [i for i, part in enumerate(where_parts) if part in {"tests", "test"}]
        if not roots:
            continue
        at = roots[-1]
        parent = where_parts[:at]
        if parts[: len(parent)] == parent and where_parts[at + 1 :] == below:
            matched.append(test)
    return sorted(matched)


class NodeCodeReader:
    suffixes: tuple[str, ...] = SUFFIXES

    def __init__(self, members: Callable[[Path], list[str]]) -> None:
        self._members = members

    def _member_names(self, root: Path) -> dict[str, str]:
        names: dict[str, str] = {}
        for member in self._members(root):
            try:
                name = json.loads((root / member / "package.json").read_text()).get("name")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(name, str) and member != ".":
                names[name] = member
        return names

    def read(self, root: Path, sources: Sequence[str], tests: Sequence[str]) -> Reading:
        paths = [p for p in sources if not p.endswith(".d.ts")]
        known = set(paths)
        members = self._member_names(root)

        def resolve(origin: str, specifier: str) -> str | None:
            bases: list[str] = []
            if specifier.startswith("."):
                bases.append(
                    posixpath.normpath(posixpath.join(posixpath.dirname(origin), specifier))
                )
            else:
                for name, folder in members.items():
                    if specifier == name:
                        bases += [f"{folder}/src/index", f"{folder}/index"]
                    elif specifier.startswith(name + "/"):
                        rest = specifier[len(name) + 1 :]
                        bases.append(posixpath.normpath(f"{folder}/{rest}"))
            for base in bases:
                for candidate in _candidates(base):
                    if candidate in known:
                        return candidate
            return None

        parsed: dict[str, tuple[Node, bytes, list[_Def]]] = {}
        files: list[FileFacts] = []
        problems: list[str] = []
        for path in paths:
            data = (root / path).read_bytes().decode(errors="replace").encode()
            lines = len(data.decode().splitlines())
            tree = parser_for(path).parse(data).root_node
            if tree.has_error:
                problems.append(f"{path}: the file could not be parsed")
                files.append(FileFacts(path=path, lines=lines, tests=tuple(_tests_of(path, tests))))
                continue
            defs = _definitions(data, tree)
            parsed[path] = (tree, data, defs)
            files.append(
                FileFacts(
                    path=path,
                    lines=lines,
                    symbols=tuple(d.symbol for d in defs),
                    tests=tuple(_tests_of(path, tests)),
                )
            )
        names = {path: {d.symbol.name for d in defs} for path, (_, _, defs) in parsed.items()}
        edges: set[tuple[str, str, str]] = set()
        for path, (tree, _, defs) in parsed.items():
            for specifier in _module_specifiers(tree):
                target = resolve(path, specifier)
                if target is not None and target != path:
                    edges.add(("imports", path, target))
            imported: dict[str, tuple[str, str]] = {}
            for local, specifier, name in _bindings(tree):
                target = resolve(path, specifier)
                if target is not None:
                    imported[local] = (target, name)

            def lookup(name: str, path: str = path, imported: dict = imported) -> str | None:
                if name in names[path]:
                    return f"{path}::{name}"
                bound = imported.get(name)
                if bound and bound[1] != "*" and bound[0] in names and bound[1] in names[bound[0]]:
                    return f"{bound[0]}::{bound[1]}"
                return None

            def member(obj: Node, prop: str, owner: str, path: str = path, imported=imported):
                within = owner.partition("::")[2]
                if obj.type == "this" and "." in within:
                    name = f"{within.split('.')[0]}.{prop}"
                    return f"{path}::{name}" if name in names[path] else None
                bound = imported.get(_text(obj)) if obj.type == "identifier" else None
                if bound and bound[1] == "*" and bound[0] in names and prop in names[bound[0]]:
                    return f"{bound[0]}::{prop}"
                return None

            owners = {(d.owner.start_byte, d.owner.end_byte, d.owner.type): d for d in defs}
            stack: list[tuple[Node, str]] = [(tree, path)]
            while stack:
                node, owner = stack.pop()
                key = (node.start_byte, node.end_byte, node.type)
                if key in owners:
                    definition = owners[key]
                    owner = f"{path}::{definition.symbol.name}"
                    if definition.heritage is not None:
                        extends = _extends(definition.heritage)
                        base = lookup(_text(extends)) if extends is not None else None
                        if extends is not None and extends.type == "identifier" and base:
                            edges.add(("inherits", owner, base))
                target = None
                if node.type == "call_expression":
                    target = _call_target(
                        node.child_by_field_name("function"), lookup, member, owner
                    )
                elif node.type == "new_expression":
                    target = _call_target(
                        node.child_by_field_name("constructor"), lookup, member, owner
                    )
                elif node.type in {"jsx_self_closing_element", "jsx_opening_element"}:
                    name = node.child_by_field_name("name")
                    target = (
                        lookup(_text(name))
                        if name is not None and name.type == "identifier"
                        else None
                    )
                if target is not None:
                    edges.add(("invokes", owner, target))
                stack.extend((child, owner) for child in node.children)
        return Reading(
            files=tuple(files),
            edges=tuple(Edge(kind=k, source=s, target=t) for k, s, t in sorted(edges)),
            problems=tuple(problems),
        )


def _extends(cls: Node) -> Node | None:
    for child in cls.named_children:
        if child.type == "class_heritage":
            for clause in child.named_children:
                if clause.type == "extends_clause":
                    return clause.child_by_field_name("value")
    return None


def _call_target(
    function: Node | None, lookup: Callable, member: Callable, owner: str
) -> str | None:
    if function is None:
        return None
    if function.type == "identifier":
        return lookup(_text(function))
    if function.type == "member_expression":
        obj = function.child_by_field_name("object")
        prop = function.child_by_field_name("property")
        if obj is not None and prop is not None:
            return member(obj, _text(prop), owner)
    return None
