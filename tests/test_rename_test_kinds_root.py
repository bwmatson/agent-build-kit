"""The rename tool works under another root and can list what it would change (spec:
test-kind-names, "Another repository's documents")."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import rename_test_kinds
from tests.factories import commit_files, init_repo

PLANNING = {
    "docs/notes.md": "Set tier2_splits for tier 1 runs.\n",
    "abk.yaml": "tier2_splits: []\n",
    "src/tier2_gate.py": "TIER2_MARKER = 1\n",
}


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "planning")
    commit_files(root, "seed", PLANNING)
    return root


def test_another_root_has_its_markdown_and_yaml_rewritten_and_no_module_renamed(
    planning: Path, tmp_path: Path
) -> None:
    framework = init_repo(tmp_path / "framework")
    commit_files(framework, "seed", {"x.md": "x\n"})

    code = rename_test_kinds.main(
        ["--root", str(planning), "--paths", str(planning / "docs"), str(planning / "abk.yaml")],
        root=framework,
    )

    assert code == 0
    assert (planning / "docs/notes.md").read_text() == "Set e2e_splits for unit-test runs.\n"
    assert (planning / "abk.yaml").read_text() == "e2e_splits: []\n"
    assert (planning / "src/tier2_gate.py").read_text() == "TIER2_MARKER = 1\n"


def test_a_path_outside_the_given_root_is_refused_and_nothing_changes(
    planning: Path, tmp_path: Path
) -> None:
    other = init_repo(tmp_path / "other")
    commit_files(other, "seed", {"a.md": "tier 2\n"})

    code = rename_test_kinds.main(
        ["--root", str(planning), "--paths", str(planning / "docs"), str(other / "a.md")],
        root=other,
    )

    assert code == 2
    assert (planning / "docs/notes.md").read_text() == PLANNING["docs/notes.md"]
    assert (other / "a.md").read_text() == "tier 2\n"


def test_dry_run_lists_the_changes_and_writes_nothing(
    planning: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = rename_test_kinds.main(
        ["--root", str(planning), "--dry-run", "--paths", str(planning)], root=planning
    )

    assert code == 0
    listed = capsys.readouterr().out.split()
    assert {"docs/notes.md", "abk.yaml", "src/e2e_gate.py"} <= set(listed)
    for name, text in PLANNING.items():
        assert (planning / name).read_text() == text
    assert (planning / "src/tier2_gate.py").exists()
    assert not (planning / "src/e2e_gate.py").exists()
