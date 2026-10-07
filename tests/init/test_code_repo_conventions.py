"""`write_code_repo_conventions`: the changelog convention block, the changelog file and the
union-merge rule that init puts into each code repo, and what it leaves alone."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig, WorkspaceConfig
from agent_build_kit.init.scaffold import ConventionResult, write_code_repo_conventions
from agent_build_kit.pipeline.changelog_convention import (
    changelog_convention,
    packaged_convention,
)
from tests.factories import git, init_repo

BLOCK = re.compile(r"<!-- abk:changelog v(?P<stamp>\w+) -->\n.*?<!-- /abk:changelog -->\n?", re.S)
RULE = "CHANGELOG.md merge=union"


def workspace(tmp_path: Path, **repos: str | None) -> WorkspaceConfig:
    """One repo per keyword, named for it, its value the `changelog` setting."""
    return WorkspaceConfig(
        repos={
            name: RepoConfig(path=tmp_path / name, slug=f"example/{name}", changelog=changelog)
            for name, changelog in repos.items()
        }
    )


def repo(tmp_path: Path, name: str = "app", **files: str | bytes) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        data = content if isinstance(content, bytes) else content.encode()
        (root / relative.replace("__", "/")).write_bytes(data)
    return root


def run(tmp_path: Path, changelog: str | None = "CHANGELOG.md", name: str = "app"):
    return write_code_repo_conventions(workspace(tmp_path, **{name: changelog}))


def outcome(results: list[ConventionResult], action: str) -> ConventionResult:
    (found,) = [r for r in results if r.action == action]
    return found


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def packaged(path: str = "CHANGELOG.md") -> str:
    """The packaged convention text for a repo keeping its changelog at `path`."""
    return packaged_convention(path)


# --- 1.1 where the block goes ---------------------------------------------------


def test_the_block_is_appended_to_an_existing_agents_md_and_the_rest_is_untouched(
    tmp_path: Path,
) -> None:
    original = "# App\n\nBuild it with care.\n\n## Testing\n\nRun the tests.\n"
    root = repo(tmp_path, **{"AGENTS.md": original})

    results = run(tmp_path)

    after = (root / "AGENTS.md").read_text()
    assert after.startswith(original)
    tail = after[len(original) :]
    assert tail.startswith("\n<!-- abk:changelog")
    assert not tail.startswith("\n\n")
    assert BLOCK.fullmatch(tail.lstrip("\n"))
    assert "## Changelog" in tail
    assert packaged() in tail
    assert outcome(results, "block").result == "updated"
    assert not (root / "CLAUDE.md").exists()


def test_a_file_with_no_final_newline_gets_one_blank_line_before_the_block(
    tmp_path: Path,
) -> None:
    root = repo(tmp_path, **{"AGENTS.md": "# App"})

    run(tmp_path)

    after = (root / "AGENTS.md").read_text()
    assert after.startswith("# App\n\n<!-- abk:changelog")


def test_the_block_reads_back_as_exactly_the_packaged_text(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"AGENTS.md": "# App\n"})

    run(tmp_path)

    app = RepoConfig(path=root, slug="example/app")
    assert changelog_convention(root, app) == packaged()


def test_the_block_goes_into_claude_md_when_only_it_exists(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"CLAUDE.md": "# App\n\nNotes.\n"})

    results = run(tmp_path)

    assert BLOCK.search((root / "CLAUDE.md").read_text())
    assert (root / "CLAUDE.md").read_text().startswith("# App\n\nNotes.\n")
    assert not (root / "AGENTS.md").exists()
    assert outcome(results, "block").path == root / "CLAUDE.md"


def test_agents_md_wins_when_both_files_exist(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"AGENTS.md": "# A\n", "CLAUDE.md": "# C\n"})

    run(tmp_path)

    assert BLOCK.search((root / "AGENTS.md").read_text())
    assert (root / "CLAUDE.md").read_text() == "# C\n"


def test_agents_md_is_created_when_neither_file_exists_and_no_claude_md_is(
    tmp_path: Path,
) -> None:
    root = repo(tmp_path)

    results = run(tmp_path)

    text = (root / "AGENTS.md").read_text()
    assert BLOCK.search(text)
    assert packaged() in text
    assert not (root / "CLAUDE.md").exists()
    assert outcome(results, "block").result == "created"


def test_crlf_endings_are_kept(tmp_path: Path) -> None:
    original = b"# App\r\n\r\nBuild it.\r\n"
    root = repo(tmp_path, **{"AGENTS.md": original})

    run(tmp_path)

    after = (root / "AGENTS.md").read_bytes()
    assert after.startswith(original + b"\r\n<!-- abk:changelog")
    assert b"\n" not in after.replace(b"\r\n", b"")


# --- 1.2 idempotence, stamps and the repo's own section --------------------------


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"AGENTS.md": "# App\n"})
    run(tmp_path)
    before = snapshot(root)

    results = run(tmp_path)

    assert snapshot(root) == before
    assert {r.result for r in results} == {"unchanged"}
    assert {r.action for r in results} == {"block", "changelog", "gitattributes"}


def test_a_block_with_an_older_stamp_has_only_its_marked_text_replaced(tmp_path: Path) -> None:
    head = "# App\n\nBefore the block.\n\n"
    old = "<!-- abk:changelog v0 -->\n## Changelog\nan older wording\n<!-- /abk:changelog -->\n"
    tail = "\n## After\n\nAfter the block.\n"
    root = repo(tmp_path, **{"AGENTS.md": head + old + tail})

    results = run(tmp_path)

    after = (root / "AGENTS.md").read_text()
    assert after.startswith(head)
    assert after.endswith(tail)
    assert "an older wording" not in after
    assert packaged() in after
    (block,) = BLOCK.findall(after)
    assert block != "0"
    assert outcome(results, "block").result == "updated"


def test_a_block_with_the_current_stamp_but_another_body_is_replaced(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"AGENTS.md": "# App\n"})
    run(tmp_path)
    written = (root / "AGENTS.md").read_text()
    edited = written.replace(packaged(), "somebody edited this")
    (root / "AGENTS.md").write_text(edited)

    results = run(tmp_path)

    assert (root / "AGENTS.md").read_text() == written
    assert outcome(results, "block").result == "updated"


def test_a_repos_own_changelog_section_outside_the_markers_gets_no_block(tmp_path: Path) -> None:
    original = "# App\n\n## Changelog\n\nOur own rules for entries.\n"
    root = repo(tmp_path, **{"AGENTS.md": original})

    results = run(tmp_path)

    assert (root / "AGENTS.md").read_bytes() == original.encode()
    assert outcome(results, "block").result == "skipped"


@pytest.mark.parametrize(
    "text",
    [
        "# App\n\n<!-- abk:changelog v1 -->\n## Changelog\nno closing marker\n",
        "# App\n\n## Changelog\nno opening marker\n<!-- /abk:changelog -->\n",
    ],
    ids=["opening-only", "closing-only"],
)
def test_mismatched_markers_are_reported_and_left_alone(tmp_path: Path, text: str) -> None:
    root = repo(tmp_path, **{"AGENTS.md": text})

    results = run(tmp_path)

    assert (root / "AGENTS.md").read_text() == text
    block = outcome(results, "block")
    assert block.result == "skipped"
    assert block.note


# --- 1.3 the changelog file -----------------------------------------------------


def test_the_changelog_is_created_when_absent(tmp_path: Path) -> None:
    root = repo(tmp_path)

    results = run(tmp_path)

    assert (root / "CHANGELOG.md").read_text().startswith("# Changelog\n\n## Unreleased")
    assert outcome(results, "changelog").result == "created"
    assert outcome(results, "changelog").path == root / "CHANGELOG.md"


def test_an_existing_changelog_is_never_edited(tmp_path: Path) -> None:
    content = "Release notes, in no form init knows.\n- a thing\n"
    root = repo(tmp_path, **{"CHANGELOG.md": content})

    results = run(tmp_path)

    assert (root / "CHANGELOG.md").read_text() == content
    assert outcome(results, "changelog").result == "unchanged"


def test_a_path_other_than_changelog_md_is_honoured_throughout(tmp_path: Path) -> None:
    root = repo(tmp_path)

    run(tmp_path, changelog="docs/HISTORY.md")

    assert (root / "docs" / "HISTORY.md").read_text().startswith("# Changelog\n\n## Unreleased")
    assert not (root / "CHANGELOG.md").exists()
    assert (root / ".gitattributes").read_text() == "docs/HISTORY.md merge=union\n"
    assert "docs/HISTORY.md" in (root / "AGENTS.md").read_text()


# --- 1.4 .gitattributes ---------------------------------------------------------


def test_gitattributes_is_created_with_the_rule_when_absent(tmp_path: Path) -> None:
    root = repo(tmp_path)

    results = run(tmp_path)

    assert (root / ".gitattributes").read_text() == f"{RULE}\n"
    assert outcome(results, "gitattributes").result == "created"


def test_the_rule_is_appended_and_the_other_lines_are_untouched(tmp_path: Path) -> None:
    original = "*.png binary\n# a comment\n*.sh text eol=lf\n"
    root = repo(tmp_path, **{".gitattributes": original})

    results = run(tmp_path)

    assert (root / ".gitattributes").read_text() == f"{original}{RULE}\n"
    assert outcome(results, "gitattributes").result == "updated"


def test_a_missing_final_newline_is_added_before_the_rule(tmp_path: Path) -> None:
    root = repo(tmp_path, **{".gitattributes": "*.png binary"})

    run(tmp_path)

    assert (root / ".gitattributes").read_text() == f"*.png binary\n{RULE}\n"


def test_a_rule_for_another_path_is_not_a_conflict(tmp_path: Path) -> None:
    original = "docs/CHANGELOG.md merge=ours\n"
    root = repo(tmp_path, **{".gitattributes": original})

    run(tmp_path)

    assert (root / ".gitattributes").read_text() == f"{original}{RULE}\n"


def test_a_present_rule_is_left_and_never_duplicated(tmp_path: Path) -> None:
    original = f"*.png binary\n{RULE}\n"
    root = repo(tmp_path, **{".gitattributes": original})

    results = run(tmp_path)

    assert (root / ".gitattributes").read_text() == original
    assert outcome(results, "gitattributes").result == "unchanged"


def test_an_anchored_rule_counts_as_the_rule_and_is_not_duplicated(tmp_path: Path) -> None:
    original = "/CHANGELOG.md merge=union\n"
    root = repo(tmp_path, **{".gitattributes": original})

    results = run(tmp_path)

    assert (root / ".gitattributes").read_text() == original
    assert outcome(results, "gitattributes").result == "unchanged"


@pytest.mark.parametrize("line", ["CHANGELOG.md merge=ours", "CHANGELOG.md -diff merge=text"])
def test_a_conflicting_merge_attribute_is_reported_and_left(tmp_path: Path, line: str) -> None:
    original = f"*.png binary\n{line}\n"
    root = repo(tmp_path, **{".gitattributes": original})

    results = run(tmp_path)

    assert (root / ".gitattributes").read_text() == original
    found = outcome(results, "gitattributes")
    assert found.result == "skipped"
    assert "merge" in found.note


# --- 1.5 the setting off, and what is not a repo ---------------------------------


def test_a_repo_with_the_setting_off_is_skipped_by_all_three_actions(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"AGENTS.md": "# App\n"})
    before = snapshot(root)

    results = run(tmp_path, changelog=None)

    assert snapshot(root) == before
    assert all(r.result == "skipped" for r in results)


def test_only_the_repo_with_the_setting_off_is_skipped(tmp_path: Path) -> None:
    off = repo(tmp_path, "off")
    on = repo(tmp_path, "on")

    write_code_repo_conventions(workspace(tmp_path, off=None, on="CHANGELOG.md"))

    assert snapshot(off) == {}
    assert (on / "AGENTS.md").exists()


def test_a_listed_repo_without_a_checkout_is_passed_over(tmp_path: Path) -> None:
    on = repo(tmp_path, "on")

    results = write_code_repo_conventions(
        workspace(tmp_path, gone="CHANGELOG.md", on="CHANGELOG.md")
    )

    assert not (tmp_path / "gone").exists()
    assert (on / "AGENTS.md").exists()
    assert {r.repo for r in results if r.result != "skipped"} == {"on"}


def test_nothing_is_committed(tmp_path: Path) -> None:
    root = init_repo(tmp_path / "app")
    (root / "README.md").write_text("app\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    head = git(root, "rev-parse", "HEAD")

    run(tmp_path)

    assert git(root, "rev-parse", "HEAD") == head
    assert git(root, "status", "--porcelain")


# --- dry run --------------------------------------------------------------------


def test_a_dry_run_writes_nothing_and_reports_what_a_real_run_then_does(tmp_path: Path) -> None:
    root = repo(tmp_path, **{"AGENTS.md": "# App\n", ".gitattributes": "*.png binary\n"})
    before = snapshot(root)

    planned = write_code_repo_conventions(workspace(tmp_path, app="CHANGELOG.md"), dry_run=True)

    assert snapshot(root) == before
    assert {r.result for r in planned} == {"created", "updated"}
    assert write_code_repo_conventions(workspace(tmp_path, app="CHANGELOG.md")) == planned
