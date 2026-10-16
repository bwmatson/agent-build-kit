"""With shims the rename tool leaves the old module and names importable, and `--remove-shims`
takes them away (spec: test-kind-names, "A slice leaves the rest importing", "Shims removed")."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit import rename_test_kinds
from tests.factories import commit_files, init_repo

CONSUMER = """\
from pkg import tier2_gate as old_module
from pkg import e2e_gate
from pkg.tier2_gate import TIER2_MARKER, Tier2Result

assert old_module.Tier2Result is e2e_gate.E2eResult
assert Tier2Result is e2e_gate.E2eResult
assert TIER2_MARKER == e2e_gate.E2E_MARKER == 7
print("imported")
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "repo")
    commit_files(
        root,
        "seed",
        {
            "pkg/__init__.py": "",
            "pkg/tier2_gate.py": "class Tier2Result:\n    pass\n\n\nTIER2_MARKER = 7\n",
            "other/__init__.py": "",
            "other/consumer.py": CONSUMER,
        },
    )
    return root


def run_module(repo: Path, module: str) -> subprocess.CompletedProcess[str]:
    code = f"import sys; sys.path.insert(0, {str(repo)!r}); import {module}"
    return subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )


def test_an_unconverted_file_still_imports_the_old_names_after_a_shimmed_run(repo: Path) -> None:
    rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True)

    result = run_module(repo, "other.consumer")

    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout


def test_the_renamed_module_is_real_and_the_old_module_is_a_one_line_re_export(
    repo: Path,
) -> None:
    rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True)

    assert "class E2eResult" in (repo / "pkg/e2e_gate.py").read_text()
    shim = (repo / "pkg/tier2_gate.py").read_text().strip().splitlines()
    assert len(shim) == 1
    assert "e2e_gate" in shim[0]


def test_remove_shims_deletes_the_aliases_and_the_shim_modules(repo: Path) -> None:
    rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True)

    rename_test_kinds.rename_paths(repo, [repo / "pkg"], remove_shims=True)

    assert not (repo / "pkg/tier2_gate.py").exists()
    assert "Tier2Result" not in (repo / "pkg/e2e_gate.py").read_text()
    assert "TIER2_MARKER" not in (repo / "pkg/e2e_gate.py").read_text()
    assert run_module(repo, "pkg.tier2_gate").returncode != 0
    assert run_module(repo, "pkg.e2e_gate").returncode == 0
    assert run_module(repo, "other.consumer").returncode != 0
