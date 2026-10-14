"""The host-address and diff-hunk patterns are each defined once and imported by the
other modules that use them, and each matches what every copy matched."""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterable
from types import ModuleType

from agent_build_kit.forges import github
from agent_build_kit.init import detect
from agent_build_kit.pipeline import own_tests, ui_review
from agent_build_kit.serve import review

ORIGIN = r"^(?:[\w.@-]+:(?!//)|[a-z+]+://[^/]+/)(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"
HUNK = r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"


def holders(source: str, modules: Iterable[ModuleType]) -> dict[str, tuple[str, bool]]:
    """For each module, the name it holds a pattern of `source` under and whether
    its own code assigns that name (a definition) rather than importing it."""
    found: dict[str, tuple[str, bool]] = {}
    for module in modules:
        names = [
            name
            for name, value in vars(module).items()
            if isinstance(value, re.Pattern) and value.pattern == source
        ]
        assert names, f"{module.__name__} holds no pattern {source!r}"
        tree = ast.parse(inspect.getsource(module))
        assigned = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        found[module.__name__] = (names[0], names[0] in assigned)
    return found


REMOTES = [
    ("git@github.com:example/app.git", "example", "app"),
    ("https://github.com/example/app", "example", "app"),
    ("ssh://git@github.com/example/app.git", "example", "app"),
    ("deploy-alias:example/platform.git", "example", "platform"),
    ("https://github.com/example/app/", "example", "app"),
]
DIFF = "diff --git a/x b/x\n@@ -1,2 +3 @@ def f\n+x\n@@ -10 +12,4 @@\n"
HUNKS = [("1", "2", "3", None), ("10", None, "12", "4")]


def test_the_host_address_pattern_is_defined_once_and_reads_every_remote() -> None:
    modules = [detect, github]
    held = holders(ORIGIN, modules)

    assert sum(defined for _, defined in held.values()) == 1
    for module in modules:
        pattern = getattr(module, held[module.__name__][0])
        for url, owner, name in REMOTES:
            match = pattern.match(url)
            assert match is not None, f"{module.__name__} did not read {url}"
            assert (match["owner"], match["name"]) == (owner, name)


def test_the_diff_hunk_pattern_is_defined_once_and_reads_every_hunk_head() -> None:
    modules = [own_tests, ui_review, review]
    held = holders(HUNK, modules)

    assert sum(defined for _, defined in held.values()) == 1
    for module in modules:
        pattern = getattr(module, held[module.__name__][0])
        assert [m.groups() for m in pattern.finditer(DIFF)] == HUNKS, module.__name__
        assert pattern.search("not a hunk") is None
