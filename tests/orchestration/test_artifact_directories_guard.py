"""No module outside the local Artifacts implementation opens a path under the artifact directories.

The run logs, e2e output, failure bundles, transcripts and spec snapshots are reached by key
through the Artifacts interface, so that a deployment with no state directory on a disk reads
and writes them too. A module that still builds a path under one of those directories works on a
machine and fails in the cloud; this scan names it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.tracked_files import ROOT, guarded_files

SOURCE = Path("src") / "agent_build_kit"
LOCAL_IMPLEMENTATION = SOURCE / "orchestration" / "local"

# The directories under the state directory that hold artifacts, as they are named on disk.
ARTIFACT_DIRECTORIES = frozenset(
    {"unit-logs", "e2e-output", "test-failures", "transcripts", "spec-snapshots"}
)
# The helpers that return a path under one of them.
DIRECTORY_HELPERS = frozenset(
    {
        "run_log_dir",
        "e2e_output_dir",
        "failure_bundles_dir",
        "transcript_dir",
        "snapshot_dir",
        "unit_transcript_files",
    }
)


def _called(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def opens_an_artifact_path(tree: ast.AST) -> bool:
    """Whether the module calls a helper returning an artifact directory, or joins one of the
    directories' names onto a path with `/`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called(node) in DIRECTORY_HELPERS:
            return True
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and node.right.value in ARTIFACT_DIRECTORIES
        ):
            return True
    return False


@pytest.mark.integration
def test_no_module_outside_the_local_implementation_opens_an_artifact_path() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in guarded_files(under=[SOURCE.as_posix()], suffixes={".py"})
        if LOCAL_IMPLEMENTATION not in path.relative_to(ROOT).parents
        and opens_an_artifact_path(ast.parse(path.read_text()))
    ]

    assert offenders == [], (
        "these modules open a path under an artifact directory instead of going through the "
        f"Artifacts interface: {', '.join(offenders)}"
    )
