"""A test carrying the markers of two splits is found by listing alone, with no plugin of the
repo loaded (spec: tier2-splits, "No plugin of the repo")."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_build_kit.config import Tier2Split
from agent_build_kit.pipeline.e2e_exclusive import check_splits
from agent_build_kit.profiles.python_uv import PROFILE

SPLITS = (
    Tier2Split(name="acp", marker="runtime_acp"),
    Tier2Split(name="claude_code", marker="runtime_claude_code"),
    Tier2Split(name="rest"),
)
COMMAND = [sys.executable, "-m", "pytest", "-m", "local_stack"]


def repo(root: Path, body: str) -> Path:
    (root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        'markers = ["local_stack", "runtime_acp", "runtime_claude_code"]\n'
    )
    (root / "test_live.py").write_text("import pytest\n\n" + body)
    return root


def check(root: Path) -> Any:
    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.run(argv, cwd=root, **kwargs)

    return check_splits(PROFILE, COMMAND, "local_stack", SPLITS, run=run)


def test_a_test_carrying_the_markers_of_two_splits_is_found_in_both(tmp_path: Path) -> None:
    root = repo(
        tmp_path,
        "@pytest.mark.local_stack\n@pytest.mark.runtime_acp\n@pytest.mark.runtime_claude_code\n"
        "def test_both(): ...\n",
    )

    (finding,) = check(root).findings

    assert "test_live.py::test_both" in finding
    assert "acp" in finding
    assert "claude_code" in finding


def test_a_test_carrying_one_marker_is_not_found(tmp_path: Path) -> None:
    root = repo(
        tmp_path,
        "@pytest.mark.local_stack\n@pytest.mark.runtime_acp\ndef test_one(): ...\n\n"
        "@pytest.mark.local_stack\ndef test_plain(): ...\n",
    )

    result = check(root)

    assert result.findings == ()
    assert {listing.name: len(listing.tests or ()) for listing in result.listings} == {
        "acp": 1,
        "claude_code": 0,
        "rest": 1,
    }
