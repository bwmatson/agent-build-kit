"""The selector check the build runs at the tests commit of an `[integration-test]` group names
each test the commit adds that lacks the `integration` selector (spec: test-markers).

Over real git repositories and the Python profile's own test paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.wiring import build_selector_check
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import commit_files, git, init_repo

SUBJECT = "tests/test_subject.py"
BARE = "def test_new():\n    assert False\n"
DECORATED = "import pytest\n\n\n@pytest.mark.integration\ndef test_new():\n    assert False\n"
MODULE_WIDE = (
    "import pytest\n\npytestmark = pytest.mark.integration\n\n\ndef test_new():\n    assert False\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    commit_files(work, "base", {"README.md": "base\n"})
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


def test_a_test_with_no_selector_is_named_with_the_selector(repo: Path) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: BARE})

    ok, reason = build_selector_check(profile=PYTHON)(cwd=repo)

    assert not ok
    assert "test_new" in reason
    assert "integration" in reason


@pytest.mark.parametrize("text", [DECORATED, MODULE_WIDE], ids=["decorator", "module-wide"])
def test_a_test_with_the_selector_passes(repo: Path, text: str) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: text})

    ok, reason = build_selector_check(profile=PYTHON)(cwd=repo)

    assert ok, reason
