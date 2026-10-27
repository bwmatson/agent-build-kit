"""Guard support: a test module that builds a child pytest's source as a string.

A module that holds a string constant defining a test, a fixture or a pytest hook and also calls
a function that runs or collects such a source keeps the child's code where no linter reads it.
The child's code belongs in files under `tests/child_modules/<scenario>/`, run with
`tests/child_pytest.py` `run_scenario`. The modules that still build a source as a string are in
`ALLOWED`; the list only shrinks. A name in `RUNNERS` is a name, not a type, so a false hit is
fixed by an `ALLOWED` entry with its reason, never by loosening the detector.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from tests.tracked_files import ROOT

CHILD_MODULES = "tests/child_modules/"
DEFINES_A_TEST = re.compile(r"^[ \t]*(def (test_|pytest_)|@pytest\.fixture)", re.MULTILINE)

RUNNERS = frozenset(
    {
        "makepyfile",
        "makeconftest",
        "runpytest",
        "runpytest_inprocess",
        "runpytest_subprocess",
        "inline_run",
        "inline_genitems",
        "run_child",
        "run_children",
        "run_session",
        "run_pytest",
        "collected",
        "drifted",
        "collect",
    }
)

REASON = "builds a child's source as a string; migrate to tests/child_modules"
ALLOWED: Mapping[str, str] = {
    "tests/profiles/test_python_uv_e2e_durations_real_pytest.py": REASON,
    "tests/profiles/test_python_uv_e2e_summary_real_pytest.py": REASON,
    "tests/profiles/test_python_uv_repeat_command.py": REASON,
    "tests/replay/test_replay_label.py": REASON,
    "tests/replay/test_replay_plugin.py": REASON,
    "tests/replay/test_replay_proxy_lifetime.py": REASON,
    "tests/replay/test_replay_unit_build_tier.py": REASON,
    "tests/test_agent_start_signals.py": REASON,
    "tests/test_claude_without_acp_gap_list.py": REASON,
    "tests/test_e2e_time_split.py": REASON,
    "tests/test_live_tests_across_dimensions.py": REASON,
    "tests/test_live_tests_are_tagged.py": REASON,
    "tests/test_live_tests_use_shared_tick.py": REASON,
    "tests/test_openspec_cli_probe.py": REASON,
    "tests/test_runtime_tag_agrees_with_start.py": REASON,
    "tests/test_runtime_tag_rule.py": REASON,
    "tests/test_runtime_tags_registered.py": REASON,
    "tests/test_scratch_dump.py": REASON,
    "tests/test_scratch_dump_bounds.py": REASON,
    "tests/test_spawn_guards.py": REASON,
    "tests/test_time_limit.py": REASON,
    "tests/test_warning_filters.py": REASON,
}


def source_hits(text: str) -> list[int]:
    """Lines of string constants that define a test, fixture or hook, in a module that also calls
    a name of `RUNNERS`."""
    tree = ast.parse(text)
    calls_a_runner = any(
        isinstance(node, ast.Call)
        and (
            node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        )
        in RUNNERS
        for node in ast.walk(tree)
    )
    if not calls_a_runner:
        return []
    return sorted(
        {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and DEFINES_A_TEST.search(node.value)
        }
    )


def check_tests(
    files: Iterable[Path], allowed: Mapping[str, str] = ALLOWED, root: Path = ROOT
) -> list[str]:
    """`path:line` of each hit in a module not allowed, and a stale-entry line for each allowed
    module with no hit; files under `tests/child_modules/` are exempt."""
    problems: list[str] = []
    hit_modules: set[str] = set()
    for path in files:
        relative = path.relative_to(root).as_posix()
        if relative.startswith(CHILD_MODULES):
            continue
        hits = source_hits(path.read_text())
        if hits:
            hit_modules.add(relative)
        if hits and relative not in allowed:
            problems.extend(f"{relative}:{line}" for line in hits)
    problems.extend(
        f"{relative}: stale allow-list entry, the module builds no child source as a string"
        for relative in allowed
        if relative not in hit_modules
    )
    return problems
