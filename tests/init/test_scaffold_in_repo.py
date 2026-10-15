"""Laying out a planning repo that is also the code repo: kept files and marker blocks."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.init.scaffold import ScaffoldError, draft_config, write_planning_repo
from tests.factories import fake_openspec, init_repo
from tests.init.test_code_repo_conventions import snapshot
from tests.init.test_scaffold import detection

STATE_LINES = {
    "runs/*.lock",
    "runs/locks/",
    "runs/unit-logs/",
    "runs/usage-ledger.jsonl",
    "runs/decisions.jsonl",
    "runs/usage-calls.jsonl",
    "*.pre-redact",
}
IGNORE_BLOCK = re.compile(r"# abk:planning v\w+\n(?P<lines>.*?)# /abk:planning\n", re.S)
ORIENTATION = re.compile(r"<!-- abk:planning v\w+ -->\r?\n.*?<!-- /abk:planning -->\r?\n", re.S)


def in_repo_config(repo: Path) -> WorkspaceConfig:
    """The configuration `abk init . --repo .` drafts: the one repo at the planning root."""
    config = draft_config({"app": detection("app", repo.parent)}, planning_dir=repo)
    app = config.repos["app"].model_copy(update=dict(path=Path(".")))
    return config.model_copy(update=dict(repos=dict(app=app)))


def lay_out(repo: Path) -> list[Path]:
    return write_planning_repo(repo, in_repo_config(repo), run_openspec=fake_openspec)


def repo_with(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    repo = init_repo(tmp_path / "app")
    for name, text in (files or {}).items():
        (repo / name).write_text(text)
    return repo


def test_an_existing_store_is_untouched_and_a_second_run_writes_nothing(tmp_path: Path) -> None:
    repo = repo_with(tmp_path)
    (repo / "runs").mkdir()
    store = b'{"units": [{"id": "feature/1"}]}'
    (repo / "runs" / "units.json").write_bytes(store)

    first = lay_out(repo)
    after_first = snapshot(repo)
    second = lay_out(repo)

    assert (repo / "runs" / "units.json").read_bytes() == store
    assert repo / "abk.yaml" in first
    assert second == []
    assert snapshot(repo) == after_first


def test_the_gitignore_gains_one_block_of_exactly_the_missing_lines(tmp_path: Path) -> None:
    original = "# mine\n.venv/\nruns/unit-logs/\n"
    repo = repo_with(tmp_path, {".gitignore": original})

    lay_out(repo)

    text = (repo / ".gitignore").read_text()
    blocks = list(IGNORE_BLOCK.finditer(text))
    assert len(blocks) == 1
    assert set(blocks[0]["lines"].split()) == STATE_LINES - {"runs/unit-logs/"}
    assert IGNORE_BLOCK.sub("", text) == original
    assert text.count("runs/unit-logs/") == 1
    lay_out(repo)
    assert (repo / ".gitignore").read_text() == text


def test_a_gitignore_that_is_missing_is_created_with_the_block(tmp_path: Path) -> None:
    repo = repo_with(tmp_path)

    lay_out(repo)

    blocks = list(IGNORE_BLOCK.finditer((repo / ".gitignore").read_text()))
    assert len(blocks) == 1
    assert set(blocks[0]["lines"].split()) == STATE_LINES


def test_an_older_ignore_block_is_refreshed_in_place(tmp_path: Path) -> None:
    before, after = "# top\nbuild/\n", "dist/\n"
    old = "# abk:planning v0\nruns/unit-logs/\n# /abk:planning\n"
    repo = repo_with(tmp_path, {".gitignore": before + old + after})

    lay_out(repo)

    text = (repo / ".gitignore").read_text()
    assert text.startswith(before) and text.endswith(after)
    block = IGNORE_BLOCK.search(text)
    assert block and set(block["lines"].split()) == STATE_LINES
    assert len(IGNORE_BLOCK.findall(text)) == 1


def test_the_orientation_is_appended_to_an_existing_agents_file(tmp_path: Path) -> None:
    own = "# The app\n\nBuild with make.\n"
    repo = repo_with(tmp_path, {"AGENTS.md": own})

    lay_out(repo)

    text = (repo / "AGENTS.md").read_text()
    assert len(ORIENTATION.findall(text)) == 1
    assert ORIENTATION.sub("", text).rstrip("\n") == own.rstrip("\n")
    assert text.startswith(own)
    assert not (repo / "CLAUDE.md").exists()


def test_the_orientation_goes_to_claude_md_when_only_that_exists(tmp_path: Path) -> None:
    own = "# Notes\r\nkeep me\r\n"
    repo = repo_with(tmp_path)
    (repo / "CLAUDE.md").write_bytes(own.encode())

    lay_out(repo)

    text = (repo / "CLAUDE.md").read_bytes().decode()
    assert text.startswith(own)
    assert len(ORIENTATION.findall(text)) == 1
    assert not (repo / "AGENTS.md").exists()


def test_agents_md_is_created_when_neither_file_exists(tmp_path: Path) -> None:
    repo = repo_with(tmp_path)

    lay_out(repo)

    assert len(ORIENTATION.findall((repo / "AGENTS.md").read_text())) == 1
    assert not (repo / "CLAUDE.md").exists()


def test_the_orientation_says_where_the_specs_state_and_graph_live(tmp_path: Path) -> None:
    repo = repo_with(tmp_path)

    lay_out(repo)

    block = ORIENTATION.search((repo / "AGENTS.md").read_text())
    assert block
    for word in ("abk.yaml", "openspec", "runs", "unit_graph"):
        assert word in block[0]


def test_an_older_orientation_is_replaced_in_place(tmp_path: Path) -> None:
    before, after = "# The app\n\n", "\n## Other\ntext\n"
    old = "<!-- abk:planning v0 -->\nstale words\n<!-- /abk:planning -->\n"
    repo = repo_with(tmp_path, {"AGENTS.md": before + old + after})

    lay_out(repo)

    text = (repo / "AGENTS.md").read_text()
    assert "stale words" not in text
    assert text.startswith(before) and text.endswith(after)
    assert len(ORIENTATION.findall(text)) == 1


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("AGENTS.md", "# App\n<!-- abk:planning v1 -->\nmy own rules\n"),
        ("AGENTS.md", "# App\nmy own rules\n<!-- /abk:planning -->\n"),
        (".gitignore", "build/\n# abk:planning v1\nmine/\n"),
        (".gitignore", "build/\n# /abk:planning\n"),
    ],
)
def test_mismatched_markers_leave_the_file_alone_and_say_so(
    tmp_path: Path, name: str, text: str
) -> None:
    repo = repo_with(tmp_path, {name: text})

    for _ in range(2):
        with pytest.raises(ScaffoldError, match="fix the markers by hand|fix them by hand"):
            lay_out(repo)

    assert (repo / name).read_text() == text
    assert not (repo / "abk.yaml").exists()


def test_a_file_that_is_not_utf8_is_refused_by_name(tmp_path: Path) -> None:
    repo = repo_with(tmp_path)
    (repo / "AGENTS.md").write_bytes("caf\xe9\n".encode("latin-1"))

    with pytest.raises(ScaffoldError, match="AGENTS.md is not valid UTF-8"):
        lay_out(repo)

    assert (repo / "AGENTS.md").read_bytes() == "caf\xe9\n".encode("latin-1")
