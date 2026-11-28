"""The measures of a Python source: per function its lines, parameters, nesting, cognitive
complexity and boolean operators, and per file its lines."""

import ast
from collections import Counter
from collections.abc import Iterable, Iterator

from agent_build_kit.model import Frozen

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
ScopeNode = FunctionNode | ast.ClassDef
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
LOOPS = (ast.For, ast.AsyncFor, ast.While)
BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)
IMPLICIT_FIRST = ("self", "cls")


class MeasureError(Exception):
    """A source that cannot be measured; the message names the file."""


class FunctionMeasure(Frozen):
    """One function: where it sits and the five measures the bars are set on."""

    name: str
    first_line: int
    def_line: int
    last_line: int
    lines: int
    parameters: int
    nesting: int
    cognitive_complexity: int
    boolean_operators: int


class SourceMeasure(Frozen):
    """One file: its physical lines and every function in it."""

    lines: int
    functions: tuple[FunctionMeasure, ...]


def measure_source(source: str, path: str) -> SourceMeasure:
    """Measure `source`, the text of the file `path`; raise `MeasureError` naming `path` when it
    does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as error:
        raise MeasureError(
            f"{path}: does not parse; the bars cannot be measured ({error})"
        ) from error
    seen: Counter[str] = Counter()
    functions = tuple(
        _measure_function(node, _unique_name(name, seen), in_class)
        for node, name, in_class in _functions(tree, "", False)
    )
    return SourceMeasure(lines=len(source.splitlines()), functions=functions)


def _unique_name(name: str, seen: Counter[str]) -> str:
    """`name` for its first definition; a later one takes a hash sign and its ordinal."""
    seen[name] += 1
    return name if seen[name] == 1 else f"{name}#{seen[name]}"


def _functions(
    node: ast.AST, prefix: str, in_class: bool
) -> Iterator[tuple[FunctionNode, str, bool]]:
    """Every function under `node` in source order with its qualified name and whether its
    `def` stands in a class body."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            yield from _functions(child, f"{prefix}{child.name}.", True)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child, f"{prefix}{child.name}", in_class
            yield from _functions(child, f"{prefix}{child.name}.", False)
        else:
            yield from _functions(child, prefix, in_class)


def _first_line(scope: ScopeNode) -> int:
    """The first line of a `def` or `class`: its first decorator, else the statement itself."""
    return min([scope.lineno, *(decorator.lineno for decorator in scope.decorator_list)])


def _measure_function(node: FunctionNode, name: str, in_class: bool) -> FunctionMeasure:
    first = _first_line(node)
    last = node.end_lineno or node.lineno
    return FunctionMeasure(
        name=name,
        first_line=first,
        def_line=node.lineno,
        last_line=last,
        lines=_own_lines(node, last),
        parameters=_parameters(node, in_class),
        nesting=_nesting(node.body, 0),
        cognitive_complexity=sum(_complexity(statement, 0) for statement in node.body),
        boolean_operators=max(_boolean_counts(node.body), default=0),
    )


def _nested_scopes(node: ast.AST) -> Iterator[ScopeNode]:
    """The `def` and `class` statements under `node` not inside another one."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, SCOPES):
            yield child
        else:
            yield from _nested_scopes(child)


def _own_lines(node: FunctionNode, last: int) -> int:
    """The physical lines from the `def` line to `last`, less those of nested defs and classes."""
    nested: set[int] = set()
    for scope in _nested_scopes(node):
        nested.update(range(_first_line(scope), (scope.end_lineno or scope.lineno) + 1))
    return last - node.lineno + 1 - len(nested)


def _parameters(node: FunctionNode, in_class: bool) -> int:
    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    count = len(positional) + len(arguments.kwonlyargs)
    count += (arguments.vararg is not None) + (arguments.kwarg is not None)
    if in_class and positional and positional[0].arg in IMPLICIT_FIRST:
        count -= 1
    return count


def _blocks(statement: ast.stmt) -> list[list[ast.stmt]]:
    """The statement lists a compound statement holds, each one level deeper than it."""
    if isinstance(statement, ast.Match):
        return [case.body for case in statement.cases]
    if isinstance(statement, ast.Try):
        return [
            statement.body,
            *(handler.body for handler in statement.handlers),
            statement.orelse,
            statement.finalbody,
        ]
    if isinstance(statement, (ast.If, *LOOPS)):
        return [statement.body, statement.orelse]
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        return [statement.body]
    return []


def _nesting(statements: list[ast.stmt], depth: int) -> int:
    """The deepest depth of a statement in `statements`, which sit at `depth`."""
    return max((_statement_nesting(statement, depth) for statement in statements), default=depth)


def _statement_nesting(statement: ast.stmt, depth: int) -> int:
    deepest = depth
    for block in _blocks(statement):
        if not block:
            continue
        if isinstance(statement, ast.If) and block is statement.orelse and _is_elif(statement):
            deepest = max(deepest, _statement_nesting(block[0], depth))
        else:
            deepest = max(deepest, _nesting(block, depth + 1))
    return deepest


def _is_elif(parent: ast.If) -> bool:
    """Whether the `else` of `parent` is one `elif`: a lone `if` written at its parent's column."""
    only = parent.orelse
    return (
        len(only) == 1 and isinstance(only[0], ast.If) and only[0].col_offset == parent.col_offset
    )


def _complexity(node: ast.AST, nesting: int) -> int:
    """The cognitive complexity of `node`, which sits at `nesting`."""
    if isinstance(node, SCOPES):
        return 0
    if isinstance(node, ast.If):
        return _if_complexity(node, nesting, 1 + nesting)
    if isinstance(node, (ast.IfExp, ast.For, ast.AsyncFor, ast.While, ast.Match)):
        return _structure_complexity(node, nesting)
    if isinstance(node, ast.Try):
        return _try_complexity(node, nesting)
    if isinstance(node, ast.BoolOp):
        return 1 + _operand_complexity(node, nesting)
    if isinstance(node, ast.Lambda):
        return _complexity(node.body, nesting + 1)
    if isinstance(node, ast.comprehension):
        return len(node.ifs) + _children_complexity(node, nesting)
    return _children_complexity(node, nesting)


def _children_complexity(node: ast.AST, nesting: int) -> int:
    return sum(_complexity(child, nesting) for child in ast.iter_child_nodes(node))


def _operand_complexity(node: ast.BoolOp, nesting: int) -> int:
    """The complexity under the operands of one boolean node; an operand of the same operator
    is part of its chain."""
    total = 0
    for operand in node.values:
        if isinstance(operand, ast.BoolOp) and type(operand.op) is type(node.op):
            total += _operand_complexity(operand, nesting)
        else:
            total += _complexity(operand, nesting)
    return total


def _if_complexity(node: ast.If, nesting: int, increment: int) -> int:
    total = increment + _complexity(node.test, nesting) + _sum(node.body, nesting + 1)
    chained = node.orelse[0] if _is_elif(node) else None
    if isinstance(chained, ast.If):
        return total + _if_complexity(chained, nesting, 1)
    if node.orelse:
        total += 1 + _sum(node.orelse, nesting + 1)
    return total


def _sum(nodes: Iterable[ast.AST | None], nesting: int) -> int:
    return sum(_complexity(node, nesting) for node in nodes if node is not None)


def _structure_complexity(
    node: ast.IfExp | ast.Match | ast.For | ast.AsyncFor | ast.While, nesting: int
) -> int:
    """A conditional expression, a loop or a `match`: +1 and the nesting, its bodies one deeper."""
    total = 1 + nesting
    if isinstance(node, ast.IfExp):
        return total + _sum([node.test], nesting) + _sum([node.body, node.orelse], nesting + 1)
    if isinstance(node, ast.Match):
        total += _sum([node.subject], nesting)
        for case in node.cases:
            total += _sum([case.guard], nesting) + _sum(case.body, nesting + 1)
        return total
    return total + _loop_complexity(node, nesting)


def _loop_complexity(node: ast.For | ast.AsyncFor | ast.While, nesting: int) -> int:
    """What a loop adds besides its own increment: its head, its body and its `else`."""
    head = [node.test] if isinstance(node, ast.While) else [node.target, node.iter]
    total = _sum(head, nesting) + _sum(node.body, nesting + 1)
    return total + (1 + _sum(node.orelse, nesting + 1) if node.orelse else 0)


def _try_complexity(node: ast.Try, nesting: int) -> int:
    total = _sum([*node.body, *node.finalbody], nesting)
    for handler in node.handlers:
        total += 1 + nesting + _sum([handler.type], nesting) + _sum(handler.body, nesting + 1)
    return total + (1 + _sum(node.orelse, nesting) if node.orelse else 0)


def _boolean_counts(statements: list[ast.stmt]) -> list[int]:
    """The operator count of each boolean expression in `statements`, nested scopes left out."""
    counts: list[int] = []
    for statement in statements:
        _collect_boolean(statement, False, counts)
    return counts


def _collect_boolean(node: ast.AST, operand: bool, counts: list[int]) -> None:
    if isinstance(node, SCOPES):
        return
    if isinstance(node, ast.BoolOp) and not operand:
        counts.append(_operators(node))
    passes = isinstance(node, ast.BoolOp) or (
        operand and isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)
    )
    for child in ast.iter_child_nodes(node):
        _collect_boolean(child, passes, counts)


def _operators(node: ast.AST) -> int:
    """The `and`/`or` operators in a boolean expression, `not` passed through."""
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1 + sum(_operators(value) for value in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _operators(node.operand)
    return 0
