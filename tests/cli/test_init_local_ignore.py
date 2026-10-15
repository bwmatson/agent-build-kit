"""`abk init` ignores the local scrub list and the redaction originals, and says where an
installation's stack facts go (spec: consumer-facts-in-env, scrub-check)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.cli.init_quiet import app_repo, quiet
from tests.factories import recognised_planning

FLAGS = ["--yes", "--skip-research", "--skip-propose"]
LOCAL_LINES = ["scrub.local", "*.pre-redact"]


@pytest.fixture(autouse=True)
def quiet_init(monkeypatch: pytest.MonkeyPatch) -> None:
    quiet(monkeypatch)
    for name in ("NAME", "EMAIL"):
        monkeypatch.setenv(f"GIT_AUTHOR_{name}", "t")
        monkeypatch.setenv(f"GIT_COMMITTER_{name}", "t")


def init(tmp_path: Path) -> int:
    planning = recognised_planning(tmp_path / "planning")
    return main(["init", str(planning), "--repo", str(app_repo(tmp_path)), *FLAGS])


def tree(planning: Path) -> dict[str, str]:
    return {
        str(p.relative_to(planning)): p.read_text(errors="replace")
        for p in sorted(planning.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(planning).parts
    }


def squashed(text: str) -> str:
    return " ".join(text.split())


def test_init_in_an_empty_directory_ignores_both_and_creates_neither(tmp_path: Path) -> None:
    assert init(tmp_path) == 0

    planning = tmp_path / "planning"
    lines = (planning / ".gitignore").read_text().splitlines()
    assert all(lines.count(line) == 1 for line in LOCAL_LINES)
    assert not (planning / "scrub.local").exists()
    assert not (planning / ".env").exists()


def test_an_ignore_file_missing_one_line_gets_only_that_line_and_a_rerun_changes_nothing(
    tmp_path: Path,
) -> None:
    planning = recognised_planning(tmp_path / "planning")
    (planning / ".gitignore").write_text("scrub.local\n.env\n")
    argv = ["init", str(planning), "--repo", str(app_repo(tmp_path)), *FLAGS]

    assert main(argv) == 0
    first = tree(planning)
    assert main(argv) == 0

    lines = (planning / ".gitignore").read_text().splitlines()
    assert lines.count("scrub.local") == 1
    assert lines.count("*.pre-redact") == 1
    assert lines.count(".env") == 1
    assert tree(planning) == first


def test_the_output_and_the_planning_context_say_stack_facts_go_in_the_env_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert init(tmp_path) == 0

    planning = tmp_path / "planning"
    context = squashed((planning / "openspec" / "config.yaml").read_text())
    output = squashed(capsys.readouterr().out)
    for text in (context, output):
        assert "stack" in text
        assert ".env" in text
        assert "from: env-file" in text
    assert "no other repo entries" in context


def test_the_env_example_header_names_the_local_scrub_list(tmp_path: Path) -> None:
    assert init(tmp_path) == 0

    header = (tmp_path / "planning" / ".env.example").read_text().split("\n\n", 1)[0]
    assert "scrub.local" in header
