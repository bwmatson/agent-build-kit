"""Test support: finds the lines of a test module that walk the checkout by hand."""

import ast

HELPER = "tests.tracked_files"
ROOT_NAMES = frozenset({"ROOT", "REPO_ROOT"})
WALKS = frozenset({"rglob", "glob"})


def imports_helper(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == HELPER:
            return True
        if isinstance(node, ast.Import) and any(alias.name == HELPER for alias in node.names):
            return True
    return False


def bound_from_file(tree: ast.AST) -> set[str]:
    """The names assigned from an expression that mentions `__file__`."""
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(n, ast.Name) and n.id == "__file__" for n in ast.walk(node.value))
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def hand_walks(source: str) -> list[int]:
    """The 1-based lines of a module's source that run `git ls-files`, or call `rglob` or `glob`
    on the checkout root; none when the module imports `tests.tracked_files`."""
    tree = ast.parse(source)
    if imports_helper(tree):
        return []
    roots = ROOT_NAMES | bound_from_file(tree)
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "ls-files":
            lines.add(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in WALKS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in roots
        ):
            lines.add(node.lineno)
    return sorted(lines)
