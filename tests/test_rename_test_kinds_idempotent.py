"""A second run of the rename tool changes nothing (spec: test-kind-names, "Idempotent")."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import rename_test_kinds
from tests.factories import commit_files, init_repo


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_text())
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def test_a_second_run_reports_no_file_changed_and_writes_none(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_files(
        repo, "seed", {"tier2_gate.py": "TIER2_MARKER = 1\n", "notes.md": "tier 1 and tier 2\n"}
    )
    rename_test_kinds.rename_paths(repo, [repo])
    before = snapshot(repo)

    changed = rename_test_kinds.rename_paths(repo, [repo])

    assert changed == []
    assert snapshot(repo) == before
    assert "e2e_gate.py" in before


def test_the_compatibility_module_and_its_test_are_left_untouched(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit_files(
        repo,
        "seed",
        {
            "src/agent_build_kit/compat_names.py": 'OLD = ("tier1", "tier2")\n',
            "tests/test_compat_names.py": "def test_it() -> None:\n    assert 'tier2'\n",
        },
    )

    changed = rename_test_kinds.rename_paths(repo, [repo / "src", repo / "tests"])

    assert changed == []
    assert "tier2" in (repo / "src/agent_build_kit/compat_names.py").read_text()
    assert "tier2" in (repo / "tests/test_compat_names.py").read_text()
