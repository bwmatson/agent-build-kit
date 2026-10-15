"""Editing the runtime lists of `abk.yaml` as text (spec: tier2-runtime-blocks)."""

from __future__ import annotations

import difflib
import os
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.config_text_edit import ConfigTextEditError, add_runtime, remove_runtime
from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX

BLOCKED = "runtimes_blocked"
ALLOWED = "runtimes_allowed"

HEAD = "# the planning repo\nplanning:\n  path: /work/plan  # here\n\n"
TAIL = "\n# repos below\nrepos:\n  app:\n    path: /work/app\n    slug: example/app\n"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_bytes(text.encode())
    return path


def backup_of(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def loaded(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def changes(before: str, after: str) -> tuple[list[str], list[str]]:
    """The lines removed and the lines inserted between two texts."""
    old, new = before.splitlines(keepends=True), after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    removed: list[str] = []
    inserted: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            removed += old[i1:i2]
            inserted += new[j1:j2]
    return removed, inserted


def test_add_with_no_tests_block_appends_the_block(tmp_path: Path) -> None:
    original = HEAD + TAIL
    path = write(tmp_path, original)
    edit = add_runtime(path, BLOCKED, "acp")
    assert edit.changed
    assert path.read_text().startswith(original)
    assert loaded(path)["tests"] == {BLOCKED: ["acp"]}
    assert loaded(path)["repos"] == yaml.safe_load(original)["repos"]


def test_add_with_no_tests_block_and_no_final_newline(tmp_path: Path) -> None:
    original = "planning:\n  path: /work/plan"
    path = write(tmp_path, original)
    add_runtime(path, ALLOWED, "acp")
    assert path.read_text().startswith(original)
    assert loaded(path) == {"planning": {"path": "/work/plan"}, "tests": {ALLOWED: ["acp"]}}


def test_a_repos_own_tests_block_is_not_the_top_level_one(tmp_path: Path) -> None:
    original = TAIL + "    tests:\n      tier2_runtimes: [acp]\n"
    path = write(tmp_path, original)
    add_runtime(path, BLOCKED, "acp")
    assert path.read_text().startswith(original)
    data = loaded(path)
    assert data["tests"] == {BLOCKED: ["acp"]}
    assert data["repos"]["app"]["tests"] == {"tier2_runtimes": ["acp"]}


def test_add_to_a_tests_block_without_the_list_inserts_the_key_at_its_indentation(
    tmp_path: Path,
) -> None:
    original = HEAD + "tests:\n    tier2_runtimes: [acp]  # nightly\n    other: 1\n" + TAIL
    path = write(tmp_path, original)
    add_runtime(path, BLOCKED, "acp")
    removed, inserted = changes(original, path.read_text())
    assert removed == []
    assert inserted
    assert inserted[0].startswith(f"    {BLOCKED}:")
    assert loaded(path)["tests"] == {"tier2_runtimes": ["acp"], "other": 1, BLOCKED: ["acp"]}


def test_add_to_a_block_list_uses_the_lists_own_indentation_and_quoting(tmp_path: Path) -> None:
    original = HEAD + f'tests:\n  {BLOCKED}:\n      - "acp"\n      - "claude_code"\n  other: 1\n'
    path = write(tmp_path, original)
    add_runtime(path, BLOCKED, "other_runtime")
    removed, inserted = changes(original, path.read_text())
    assert removed == []
    assert inserted == ['      - "other_runtime"\n']
    assert loaded(path)["tests"][BLOCKED] == ["acp", "claude_code", "other_runtime"]


def test_add_to_an_unquoted_block_list_at_the_keys_own_indentation(tmp_path: Path) -> None:
    original = f"tests:\n  {ALLOWED}:\n  - acp\n  - claude_code\n"
    path = write(tmp_path, original)
    add_runtime(path, ALLOWED, "x")
    assert path.read_text() == original + "  - x\n"


def test_add_to_a_block_list_keeps_a_comment_after_it(tmp_path: Path) -> None:
    original = f"tests:\n  {BLOCKED}:\n    - acp  # flaky\n    # kept\n  other: 1\n"
    path = write(tmp_path, original)
    add_runtime(path, BLOCKED, "x")
    removed, inserted = changes(original, path.read_text())
    assert removed == []
    assert [line.strip() for line in inserted] == ["- x"]
    assert loaded(path)["tests"] == {BLOCKED: ["acp", "x"], "other": 1}


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("[acp]", "[acp, x]"),
        ("[acp, claude_code]", "[acp, claude_code, x]"),
        ("[]", "[x]"),
        ("[acp]  # why", "[acp, x]  # why"),
    ],
)
def test_add_to_a_flow_list_edits_it_in_place(tmp_path: Path, before: str, after: str) -> None:
    original = HEAD + f"tests:\n  {BLOCKED}: {before}\n  other: 1\n" + TAIL
    path = write(tmp_path, original)
    add_runtime(path, BLOCKED, "x")
    assert path.read_text() == original.replace(before, after)


def test_crlf_line_endings_are_kept(tmp_path: Path) -> None:
    original = f"# c\r\ntests:\r\n  {BLOCKED}:\r\n    - acp\r\n  other: 1\r\n"
    path = write(tmp_path, original)
    add_runtime(path, BLOCKED, "x")
    assert path.read_bytes().decode() == original.replace("- acp\r\n", "- acp\r\n    - x\r\n")


def test_crlf_new_block_is_crlf(tmp_path: Path) -> None:
    original = "planning:\r\n  path: /p\r\n"
    path = write(tmp_path, original)
    add_runtime(path, BLOCKED, "x")
    text = path.read_bytes().decode()
    assert text.startswith(original)
    assert "\n" not in text.replace("\r\n", "")


def test_remove_deletes_only_the_item(tmp_path: Path) -> None:
    original = HEAD + f"tests:\n  {BLOCKED}:\n    - acp  # c\n    - x\n    - y\n" + TAIL
    path = write(tmp_path, original)
    edit = remove_runtime(path, BLOCKED, "x")
    assert edit.changed
    assert path.read_text() == original.replace("    - x\n", "")


def test_remove_the_last_item_leaves_an_empty_list(tmp_path: Path) -> None:
    original = HEAD + f"tests:\n  {BLOCKED}:\n    - acp\n  other: 1\n" + TAIL
    path = write(tmp_path, original)
    remove_runtime(path, BLOCKED, "acp")
    assert loaded(path)["tests"] == {BLOCKED: [], "other": 1}
    removed, inserted = changes(original, path.read_text())
    assert len(removed) == 2
    assert [line.strip() for line in inserted] == [f"{BLOCKED}: []"]


@pytest.mark.parametrize(
    ("before", "after"),
    [("[acp, x]", "[acp]"), ("[x, acp]", "[acp]"), ("[x]", "[]"), ("[x]  # why", "[]  # why")],
)
def test_remove_from_a_flow_list_edits_it_in_place(tmp_path: Path, before: str, after: str) -> None:
    original = f"tests:\n  {BLOCKED}: {before}\n"
    path = write(tmp_path, original)
    remove_runtime(path, BLOCKED, "x")
    assert path.read_text() == original.replace(before, after)


@pytest.mark.parametrize(
    "original",
    [
        "planning:\n  path: /p\n",
        f"tests:\n  {ALLOWED}: [x]\n",
        f"tests:\n  {BLOCKED}:\n    - acp\n",
        f"tests:\n  {BLOCKED}: []\n",
    ],
)
def test_remove_an_absent_name_changes_nothing_and_says_so(tmp_path: Path, original: str) -> None:
    path = write(tmp_path, original)
    edit = remove_runtime(path, BLOCKED, "x")
    assert not edit.changed
    assert "x" in edit.summary
    assert path.read_text() == original
    assert not backup_of(path).exists()


@pytest.mark.parametrize(
    "original",
    [
        f"tests:\n  {BLOCKED}: [acp]\n",
        f"tests:\n  {BLOCKED}:\n    - acp\n    - x\n",
        f"tests:\n  {BLOCKED}: [x, acp]  # why\n",
    ],
)
def test_adding_a_name_already_present_changes_nothing(tmp_path: Path, original: str) -> None:
    path = write(tmp_path, original)
    edit = add_runtime(path, BLOCKED, "acp")
    assert not edit.changed
    assert path.read_text() == original
    assert not backup_of(path).exists()


REFUSED = {
    "duplicate": (f"tests:\n  {BLOCKED}: [acp]\ntests:\n  {ALLOWED}: []\n", "duplicate"),
    "anchor": (f"tests:\n  {BLOCKED}: &keep [acp]\n  {ALLOWED}: *keep\n", "anchor|alias"),
    "multi-line flow": (f"tests:\n  {BLOCKED}: [acp,\n    claude_code]\n", "multi-line"),
    "not a list": (f"tests:\n  {BLOCKED}: acp\n", "not a list"),
    "no parse": (f"tests:\n  {BLOCKED}: [acp\n  other: [\n", "parse|valid yaml"),
    "anchored tests": (f"tests: &t\n  {BLOCKED}: [acp]\n", "anchor|alias"),
    "tagged tests": (f"tests: !!map\n  {BLOCKED}: [acp]\n", "tag"),
    "flow tests": ("tests: " + "{" + BLOCKED + ": [acp]}\n", "flow"),
}


@pytest.mark.parametrize("operation", [add_runtime, remove_runtime])
@pytest.mark.parametrize("layout", sorted(REFUSED))
def test_a_layout_that_cannot_be_followed_is_refused_and_left_as_it_was(
    tmp_path: Path, layout: str, operation: Any
) -> None:
    original, reason = REFUSED[layout]
    path = write(tmp_path, original)
    with pytest.raises(ConfigTextEditError, match=f"(?i){reason}"):
        operation(path, BLOCKED, "acp")
    assert path.read_bytes() == original.encode()
    assert [p.name for p in tmp_path.iterdir()] == ["abk.yaml"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only file")
@pytest.mark.parametrize("operation", [add_runtime, remove_runtime])
def test_a_read_only_file_is_refused_and_left_as_it_was(tmp_path: Path, operation: Any) -> None:
    original = f"tests:\n  {BLOCKED}: [acp]\n"
    path = write(tmp_path, original)
    path.chmod(0o444)
    with pytest.raises(ConfigTextEditError, match="(?i)read-only|writ|permission"):
        operation(path, BLOCKED, "acp")
    assert path.read_bytes() == original.encode()
    assert [p.name for p in tmp_path.iterdir()] == ["abk.yaml"]


def test_a_file_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigTextEditError):
        add_runtime(tmp_path / "abk.yaml", BLOCKED, "acp")


def test_the_original_is_copied_once_to_a_backup_beside_the_file(tmp_path: Path) -> None:
    original = HEAD + f"tests:\n  {BLOCKED}: [acp]\n" + TAIL
    path = write(tmp_path, original)
    first = add_runtime(path, BLOCKED, "x")
    assert first.backup == backup_of(path)
    assert backup_of(path).read_text() == original
    second = add_runtime(path, ALLOWED, "y")
    assert second.changed
    assert second.backup is None
    remove_runtime(path, BLOCKED, "acp")
    assert backup_of(path).read_text() == original
    assert loaded(path)["tests"] == {BLOCKED: ["x"], ALLOWED: ["y"]}


def test_the_result_is_a_document_that_loads_with_the_expected_lists(tmp_path: Path) -> None:
    before = yaml.safe_load(HEAD + TAIL)
    path = write(tmp_path, HEAD + TAIL)
    add_runtime(path, BLOCKED, "acp")
    add_runtime(path, BLOCKED, "claude_code")
    add_runtime(path, ALLOWED, "x")
    remove_runtime(path, BLOCKED, "acp")
    after = loaded(path)
    assert after["tests"] == {BLOCKED: ["claude_code"], ALLOWED: ["x"]}
    assert (after["planning"], after["repos"]) == (before["planning"], before["repos"])


def test_the_file_keeps_its_mode(tmp_path: Path) -> None:
    path = write(tmp_path, f"tests:\n  {BLOCKED}: []\n")
    path.chmod(0o640)
    add_runtime(path, BLOCKED, "acp")
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert loaded(path)["tests"][BLOCKED] == ["acp"]


# Layouts the line scan accepts but whose edit does not reload to the expected lists:
# (text, operation, name).
MISEDITED = {
    "bracket in a quoted item, add": (f'tests:\n  {BLOCKED}: ["a]b"]\n', add_runtime, "x"),
    "bracket in a quoted item, remove": (f'tests:\n  {BLOCKED}: ["a]b"]\n', remove_runtime, "a]b"),
    "keep-chomped scalar at the end, add": (
        "tests:\n  note: |+\n    text\n\n\nrepos: " + "{}" + "\n",
        add_runtime,
        "x",
    ),
}


@pytest.mark.parametrize("layout", sorted(MISEDITED))
def test_an_edit_that_does_not_reload_to_the_expected_lists_is_not_written(
    tmp_path: Path, layout: str
) -> None:
    original, operation, name = MISEDITED[layout]
    path = write(tmp_path, original)
    with pytest.raises(ConfigTextEditError, match="expected lists"):
        operation(path, BLOCKED, name)
    assert path.read_bytes() == original.encode()
    assert [p.name for p in tmp_path.iterdir()] == ["abk.yaml"]
