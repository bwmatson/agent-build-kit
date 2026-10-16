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
from pkg.tier2_gate import TIER2_MARKER, Tier2Result, _helper
import pkg

assert pkg.tier2_gate is pkg.e2e_gate
assert old_module is e2e_gate
assert _helper == 1
old_module.time = "patched"
assert e2e_gate.time == "patched"
old_module.TIER2_MARKER = 8
assert e2e_gate.TIER2_MARKER == 8

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
            "pkg/tier2_gate.py": (
                "import time\n\n\nclass Tier2Result:\n    pass\n\n\n_helper = 1\nTIER2_MARKER = 7\n"
            ),
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


def test_dry_run_with_shims_also_lists_the_old_path_it_would_recreate(repo: Path) -> None:
    changed = rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True, dry_run=True)

    assert {p.as_posix() for p in changed} == {"pkg/e2e_gate.py", "pkg/tier2_gate.py"}
    assert (repo / "pkg/tier2_gate.py").read_text().startswith("import time")


def test_shims_and_remove_shims_together_are_refused(repo: Path) -> None:
    with pytest.raises(ValueError, match="cannot both"):
        rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True, remove_shims=True)
    with pytest.raises(SystemExit):
        rename_test_kinds.main(
            ["--paths", str(repo / "pkg"), "--shims", "--remove-shims"], root=repo
        )


def test_the_shim_of_a_top_level_module_imports_without_a_package(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "flat")
    commit_files(root, "seed", {"tier2_gate.py": "VALUE = 3\n"})
    rename_test_kinds.rename_paths(root, [root], shims=True)

    assert run_module(root, "tier2_gate").returncode == 0
