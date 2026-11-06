"""A review diff is refused, not guessed, when the branch shares no history with its base."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.serve.review import NoDiff, unit_diff
from tests.factories import commit, git, init_repo


def test_a_branch_with_no_common_history_with_the_base_has_no_diff(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, "base.txt")
    git(repo, "switch", "-q", "--orphan", "unrelated")
    commit(repo, "other.txt")

    with pytest.raises(NoDiff, match="shares no history"):
        unit_diff(repo, base="main", branch="unrelated")
