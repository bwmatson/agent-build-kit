"""The e2e-test step hands the resolved ref, never the bare base, to a call that reads git: in a
code repo's checkout a bare trunk name is a local branch nothing updates (spec: unit-own-tests).
The bare name stays the rebase's and the pull request's, so those are not scanned."""

from __future__ import annotations

import ast
from pathlib import Path

import agent_build_kit.graph.nodes as nodes_module

NODES = Path(nodes_module.__file__)
# The runner calls the e2e-test step makes that read git with the base they are given.
READS_GIT = {"e2e_runs_whole", "run_e2e"}
STEP = "e2e"
CLASS = "BuildPath"


def is_resolution(node: ast.expr) -> bool:
    """`self.ref(...)`, the one resolution of a unit's base."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "ref"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    )


def resolved_names(step: ast.FunctionDef) -> set[str]:
    """The names the step binds to the resolution, whether alone or in a tuple."""
    found: set[str] = set()
    for node in ast.walk(step):
        if not isinstance(node, ast.Assign):
            continue
        targets, values = node.targets[0], node.value
        if isinstance(targets, ast.Name) and is_resolution(values):
            found.add(targets.id)
        if isinstance(targets, ast.Tuple) and isinstance(values, ast.Tuple):
            for target, value in zip(targets.elts, values.elts, strict=False):
                if isinstance(target, ast.Name) and is_resolution(value):
                    found.add(target.id)
    return found


def bare_base_calls(source: str) -> list[str]:
    """Each call in the e2e-test step that reads git and is not given the resolved ref, as
    `<call> (line <n>)`."""
    tree = ast.parse(source)
    steps = [
        node
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == CLASS
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == STEP
    ]
    assert len(steps) == 1, "the scan found no e2e-test step to read"
    resolved = resolved_names(steps[0])
    bare: list[str] = []
    for call in ast.walk(steps[0]):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
            continue
        if call.func.attr not in READS_GIT:
            continue
        given = next((kw.value for kw in call.keywords if kw.arg == "base"), None)
        ok = given is not None and (
            is_resolution(given) or (isinstance(given, ast.Name) and given.id in resolved)
        )
        if not ok:
            bare.append(f"{call.func.attr} (line {call.lineno})")
    return bare


def test_the_e2e_step_hands_the_resolved_ref_to_every_call_that_reads_git() -> None:
    assert bare_base_calls(NODES.read_text()) == []


def test_a_call_given_the_bare_base_is_named() -> None:
    source = NODES.read_text().replace(
        "r.run_e2e(cwd=tree, base=ref,", "r.run_e2e(cwd=tree, base=base,"
    )

    caught = bare_base_calls(source)

    assert len(caught) == 1 and caught[0].startswith("run_e2e (line ")


def test_a_call_with_no_base_at_all_is_named_too() -> None:
    source = NODES.read_text().replace(
        "r.e2e_runs_whole(cwd=tree, base=ref)", "r.e2e_runs_whole(cwd=tree)"
    )

    assert [c.split(" ")[0] for c in bare_base_calls(source)] == ["e2e_runs_whole"]
