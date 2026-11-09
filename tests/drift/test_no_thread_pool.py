"""The build thread pool and the pass-scoped rules are gone (spec: worker-kinds).

After the cut-over a tick admits workers and nothing else: `cli/pipeline.py` imports no
`ThreadPoolExecutor`, the pass rules (`READMITTED_CAUSES`, `REBUILDS_PER_PASS`, `_pool_size`)
and the loaded-tick bookkeeping (`running_tick`) are not defined or used anywhere in the source,
and a unit's merge tick is not compared with the loaded tick number.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.tracked_files import ROOT, guarded_files

PIPELINE_CLI = ROOT / "src/agent_build_kit/cli/pipeline.py"
UNITS = ROOT / "src/agent_build_kit/pipeline/units.py"
REMOVED_NAMES = frozenset(
    {"READMITTED_CAUSES", "REBUILDS_PER_PASS", "_pool_size", "running_tick", "ThreadPoolExecutor"}
)


def names_in(path: Path) -> list[str]:
    """Each definition, import, name or attribute of `path` that is one of the removed names."""
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        spelled: str | None = None
        if isinstance(node, ast.Name):
            spelled = node.id
        elif isinstance(node, ast.Attribute):
            spelled = node.attr
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            spelled = node.name
        elif isinstance(node, ast.alias):
            spelled = node.name.split(".")[-1]
        if spelled in REMOVED_NAMES:
            found.append(f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 0)} {spelled}")
    return found


@pytest.mark.integration
def test_no_source_file_defines_or_uses_a_pass_rule_or_the_loaded_tick_marker() -> None:
    sources = guarded_files(under=["src"], suffixes={".py"})
    # The forges' read pool is not the build pool; only the pipeline CLI must not import it.
    offences = [
        line
        for path in sources
        for line in names_in(path)
        if path == PIPELINE_CLI or not line.endswith("ThreadPoolExecutor")
    ]

    assert offences == []


def test_the_pipeline_cli_imports_no_thread_pool() -> None:
    assert [line for line in names_in(PIPELINE_CLI) if line.endswith("ThreadPoolExecutor")] == []


def test_the_merge_rule_does_not_compare_a_merge_tick_with_the_loaded_tick_number() -> None:
    compared = [
        node.lineno
        for node in ast.walk(ast.parse(UNITS.read_text()))
        if isinstance(node, ast.Compare)
        and any(
            (isinstance(part, ast.Name) and part.id == "tick")
            or (isinstance(part, ast.Attribute) and part.attr in {"merged_tick", "number"})
            for part in (node.left, *node.comparators)
        )
    ]

    assert compared == []
