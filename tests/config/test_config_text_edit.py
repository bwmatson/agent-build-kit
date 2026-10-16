"""Editing a split's `hold` in `abk.yaml` as text (spec: tier2-splits-replace-runtime-tags)."""

from __future__ import annotations

import difflib
import os
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.config_text_edit import ConfigTextEditError, set_hold
from agent_build_kit.runtimes.policy_apply import BACKUP_SUFFIX

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


def splits(path: Path) -> Any:
    return loaded(path)["tests"]["tier2_splits"]


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


BLOCK = (
    "tests:\n"
    "  tier2_splits:\n"
    "    acp:\n"
    "      marker: runtime_acp\n"
    "    claude_code:\n"
    "      marker: runtime_claude_code\n"
    "      hold: false  # off for now\n"
    "  other: 1\n"
)


def test_hold_true_on_an_entry_with_none_inserts_the_key_at_the_entrys_indentation(
    tmp_path: Path,
) -> None:
    original = HEAD + BLOCK + TAIL
    path = write(tmp_path, original)
    edit = set_hold(path, None, "acp", True)
    assert edit.changed
    removed, inserted = changes(original, path.read_text())
    assert removed == []
    assert inserted == ["      hold: true\n"]
    assert splits(path)["acp"] == {"marker": "runtime_acp", "hold": True}


def test_hold_replaces_the_value_and_keeps_the_trailing_comment(tmp_path: Path) -> None:
    original = HEAD + BLOCK + TAIL
    path = write(tmp_path, original)
    set_hold(path, None, "claude_code", True)
    assert path.read_text() == original.replace(
        "hold: false  # off for now", "hold: true  # off for now"
    )


def test_hold_false_on_a_held_entry_replaces_the_value(tmp_path: Path) -> None:
    original = "tests:\n  tier2_splits:\n    acp:\n      hold: true\n      marker: runtime_acp\n"
    path = write(tmp_path, original)
    set_hold(path, None, "acp", False)
    assert path.read_text() == original.replace("hold: true", "hold: false")


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("{marker: runtime_acp}", "{marker: runtime_acp, hold: true}"),
        ("{marker: runtime_acp}  # why", "{marker: runtime_acp, hold: true}  # why"),
        ("{marker: runtime_acp, hold: false}", "{marker: runtime_acp, hold: true}"),
        ("{hold: false, marker: runtime_acp}", "{hold: true, marker: runtime_acp}"),
    ],
)
def test_a_one_line_flow_entry_is_edited_in_place(tmp_path: Path, before: str, after: str) -> None:
    original = (
        HEAD + f"tests:\n  tier2_splits:\n    acp: {before}\n    other_split: {{marker: m}}\n"
    )
    path = write(tmp_path, original)
    set_hold(path, None, "acp", True)
    assert path.read_text() == original.replace(before, after)


REPO_AND_TOP = (
    "tests:\n"
    "  tier2_splits:\n"
    "    acp: {marker: runtime_acp}\n"
    "repos:\n"
    "  app:\n"
    "    path: /work/app\n"
    "    tests:\n"
    "      tier2_splits:\n"
    "        acp:\n"
    "          marker: runtime_acp\n"
    "  platform:\n"
    "    path: /work/platform\n"
    "    tests:\n"
    "      tier2_splits:\n"
    "        acp: {marker: runtime_acp}\n"
)


def test_setting_at_a_repos_own_splits_leaves_the_top_level_entry_alone(tmp_path: Path) -> None:
    path = write(tmp_path, REPO_AND_TOP)
    set_hold(path, "app", "acp", True)
    data = loaded(path)
    assert data["tests"]["tier2_splits"]["acp"] == {"marker": "runtime_acp"}
    assert data["repos"]["app"]["tests"]["tier2_splits"]["acp"] == {
        "marker": "runtime_acp",
        "hold": True,
    }
    assert data["repos"]["platform"]["tests"]["tier2_splits"]["acp"] == {"marker": "runtime_acp"}
    removed, inserted = changes(REPO_AND_TOP, path.read_text())
    assert removed == []
    assert inserted == ["          hold: true\n"]


def test_setting_at_the_top_leaves_every_repos_entry_alone(tmp_path: Path) -> None:
    path = write(tmp_path, REPO_AND_TOP)
    set_hold(path, None, "acp", True)
    data = loaded(path)
    assert data["tests"]["tier2_splits"]["acp"] == {"marker": "runtime_acp", "hold": True}
    assert data["repos"]["app"]["tests"]["tier2_splits"]["acp"] == {"marker": "runtime_acp"}
    assert data["repos"]["platform"]["tests"]["tier2_splits"]["acp"] == {"marker": "runtime_acp"}


def test_a_flow_entry_under_a_repo_is_edited_in_place(tmp_path: Path) -> None:
    path = write(tmp_path, REPO_AND_TOP)
    set_hold(path, "platform", "acp", True)
    assert path.read_text() == REPO_AND_TOP.replace(
        "        acp: {marker: runtime_acp}\n", "        acp: {marker: runtime_acp, hold: true}\n"
    )


def test_crlf_line_endings_are_kept(tmp_path: Path) -> None:
    original = BLOCK.replace("\n", "\r\n")
    path = write(tmp_path, original)
    set_hold(path, None, "acp", True)
    text = path.read_bytes().decode()
    assert text == original.replace(
        "marker: runtime_acp\r\n", "marker: runtime_acp\r\n      hold: true\r\n", 1
    )


def test_a_file_with_no_final_newline_keeps_that(tmp_path: Path) -> None:
    original = "tests:\n  tier2_splits:\n    acp: {marker: runtime_acp}"
    path = write(tmp_path, original)
    set_hold(path, None, "acp", True)
    assert path.read_text() == original.replace("runtime_acp}", "runtime_acp, hold: true}")


# --- removal, rest, a request that already holds, a split that is not declared ---


def test_removing_the_key_leaves_the_entry_and_its_marker(tmp_path: Path) -> None:
    original = HEAD + BLOCK + TAIL
    path = write(tmp_path, original)
    edit = set_hold(path, None, "claude_code", None)
    assert edit.changed
    assert splits(path)["claude_code"] == {"marker": "runtime_claude_code"}
    removed, inserted = changes(original, path.read_text())
    assert removed == ["      hold: false  # off for now\n"]
    assert inserted == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("{marker: m, hold: true}", "{marker: m}"),
        ("{hold: true, marker: m}", "{marker: m}"),
        ("{marker: m, hold: true}  # why", "{marker: m}  # why"),
    ],
)
def test_removing_the_key_from_a_flow_entry_keeps_the_marker(
    tmp_path: Path, before: str, after: str
) -> None:
    original = f"tests:\n  tier2_splits:\n    acp: {before}\n"
    path = write(tmp_path, original)
    set_hold(path, None, "acp", None)
    assert path.read_text() == original.replace(before, after)


def test_hold_on_rest_with_no_entry_appends_one(tmp_path: Path) -> None:
    original = HEAD + BLOCK + TAIL
    path = write(tmp_path, original)
    set_hold(path, None, "rest", True)
    assert splits(path)["rest"] == {"hold": True}
    removed, inserted = changes(original, path.read_text())
    assert removed == []
    assert inserted == ["    rest: {hold: true}\n"]
    assert loaded(path)["repos"] == yaml.safe_load(original)["repos"]


def test_hold_on_rest_creates_a_missing_e2e_splits_mapping(tmp_path: Path) -> None:
    original = "tests:\n    other: 1\n"
    path = write(tmp_path, original)
    set_hold(path, None, "rest", True)
    assert path.read_text().startswith(original)
    assert loaded(path)["tests"] == {"other": 1, "e2e_splits": {"rest": {"hold": True}}}


def test_an_entry_under_the_current_key_is_edited_in_place(tmp_path: Path) -> None:
    original = "tests:\n  e2e_splits:\n    acp:\n      marker: runtime_acp\n"
    path = write(tmp_path, original)
    set_hold(path, None, "acp", True)
    expected = {"acp": {"marker": "runtime_acp", "hold": True}}
    assert loaded(path)["tests"] == {"e2e_splits": expected}


def test_hold_on_rest_creates_a_missing_tests_mapping(tmp_path: Path) -> None:
    original = HEAD + TAIL
    path = write(tmp_path, original)
    set_hold(path, None, "rest", True)
    assert path.read_text().startswith(original)
    assert loaded(path)["tests"] == {"e2e_splits": {"rest": {"hold": True}}}
    assert loaded(path)["repos"] == yaml.safe_load(original)["repos"]


def test_hold_on_rest_with_no_final_newline_creates_the_mappings(tmp_path: Path) -> None:
    original = "planning:\n  path: /work/plan"
    path = write(tmp_path, original)
    set_hold(path, None, "rest", True)
    assert path.read_text().startswith(original)
    assert loaded(path)["tests"] == {"e2e_splits": {"rest": {"hold": True}}}


def test_hold_on_rest_at_a_repos_own_splits_appends_there(tmp_path: Path) -> None:
    path = write(tmp_path, REPO_AND_TOP)
    set_hold(path, "app", "rest", True)
    data = loaded(path)
    assert data["repos"]["app"]["tests"]["tier2_splits"]["rest"] == {"hold": True}
    assert "rest" not in data["tests"]["tier2_splits"]
    assert "rest" not in data["repos"]["platform"]["tests"]["tier2_splits"]


def test_hold_false_on_rest_with_an_entry_replaces_the_value(tmp_path: Path) -> None:
    original = "tests:\n  tier2_splits:\n    acp: {marker: m}\n    rest: {hold: true}\n"
    path = write(tmp_path, original)
    set_hold(path, None, "rest", False)
    assert path.read_text() == original.replace("rest: {hold: true}", "rest: {hold: false}")


@pytest.mark.parametrize(
    "entry",
    ["    rest: {hold: true}  # all the rest\n", "    rest:\n      hold: true\n"],
)
def test_removing_hold_from_a_rest_entry_that_holds_nothing_else_removes_the_entry(
    tmp_path: Path, entry: str
) -> None:
    kept = "tests:\n  tier2_splits:\n    acp: {marker: m}\n"
    path = write(tmp_path, kept + entry + "  other: 1\n")
    set_hold(path, None, "rest", None)
    assert path.read_text() == kept + "  other: 1\n"


def test_removing_hold_from_a_rest_entry_that_holds_something_else_keeps_it(
    tmp_path: Path,
) -> None:
    original = "tests:\n  tier2_splits:\n    rest:\n      hold: true\n      extra: 1\n"
    path = write(tmp_path, original)
    set_hold(path, None, "rest", None)
    assert path.read_text() == original.replace("      hold: true\n", "")


@pytest.mark.parametrize(
    ("original", "value"),
    [
        ("tests:\n  tier2_splits:\n    acp: {marker: m, hold: true}\n", True),
        ("tests:\n  tier2_splits:\n    acp:\n      marker: m\n      hold: false\n", False),
        ("tests:\n  tier2_splits:\n    acp: {marker: m}\n", None),
        ("tests:\n  tier2_splits:\n    rest: {hold: true}\n  other: 1\n", True),
    ],
)
def test_a_request_that_already_holds_does_nothing_and_says_so(
    tmp_path: Path, original: str, value: bool | None
) -> None:
    path = write(tmp_path, original)
    split = "rest" if "rest" in original else "acp"
    edit = set_hold(path, None, split, value)
    assert not edit.changed
    assert edit.backup is None
    assert split in edit.summary
    assert "nothing changed" in edit.summary
    assert path.read_text() == original
    assert not backup_of(path).exists()


def test_removing_hold_from_rest_with_no_entry_does_nothing(tmp_path: Path) -> None:
    original = "tests:\n  tier2_splits:\n    acp: {marker: m}\n"
    path = write(tmp_path, original)
    edit = set_hold(path, None, "rest", None)
    assert not edit.changed
    assert path.read_text() == original
    assert not backup_of(path).exists()


@pytest.mark.parametrize("value", [True, False, None])
def test_a_split_that_is_not_declared_is_refused_naming_the_declared_ones(
    tmp_path: Path, value: bool | None
) -> None:
    original = HEAD + BLOCK + TAIL
    path = write(tmp_path, original)
    with pytest.raises(
        ConfigTextEditError, match=r"(?s)ghost.*acp.*claude_code|acp.*claude_code.*ghost"
    ):
        set_hold(path, None, "ghost", value)
    assert path.read_bytes() == original.encode()
    assert not backup_of(path).exists()


def test_a_split_declared_only_at_the_top_is_not_declared_at_a_repo_with_its_own(
    tmp_path: Path,
) -> None:
    original = (
        "tests:\n  tier2_splits:\n    acp: {marker: a}\n"
        "repos:\n  app:\n    tests:\n      tier2_splits:\n        claude_code: {marker: c}\n"
    )
    path = write(tmp_path, original)
    with pytest.raises(ConfigTextEditError, match="claude_code"):
        set_hold(path, "app", "acp", True)
    assert path.read_bytes() == original.encode()


def test_a_repo_that_is_not_in_the_file_is_refused(tmp_path: Path) -> None:
    original = REPO_AND_TOP
    path = write(tmp_path, original)
    with pytest.raises(ConfigTextEditError, match="nowhere"):
        set_hold(path, "nowhere", "acp", True)
    assert path.read_bytes() == original.encode()


# --- layouts that cannot be followed ---

REFUSED = {
    "duplicate tests": (
        "tests:\n  tier2_splits:\n    acp: {marker: m}\ntests:\n  other: 1\n",
        "duplicate",
    ),
    "duplicate tier2_splits": (
        "tests:\n  tier2_splits:\n    acp: {marker: m}\n  tier2_splits:\n    b: {marker: n}\n",
        "duplicate",
    ),
    "duplicate entry": (
        "tests:\n  tier2_splits:\n    acp: {marker: m}\n    acp: {marker: n}\n",
        "duplicate",
    ),
    "anchor on the entry": (
        "tests:\n  tier2_splits:\n    acp: &keep\n      marker: m\n    other: *keep\n",
        "anchor|alias",
    ),
    "alias as the entry": (
        "base: &keep {marker: m}\ntests:\n  tier2_splits:\n    acp: *keep\n",
        "anchor|alias",
    ),
    "multi-line flow entry": (
        "tests:\n  tier2_splits:\n    acp: {marker: m,\n      hold: false}\n",
        "multi-line",
    ),
    "entry not a mapping": ("tests:\n  tier2_splits:\n    acp: runtime_acp\n", "not a mapping"),
    "no parse": ("tests:\n  tier2_splits:\n    acp: {marker: m\n  other: [\n", "parse|valid yaml"),
    "flow tests": ("tests: {tier2_splits: {acp: {marker: m}}}\n", "flow"),
    "flow tier2_splits": ("tests:\n  tier2_splits: {acp: {marker: m}}\n", "flow"),
}


@pytest.mark.parametrize("value", [True, None])
@pytest.mark.parametrize("layout", sorted(REFUSED))
def test_a_layout_that_cannot_be_followed_is_refused_and_left_as_it_was(
    tmp_path: Path, layout: str, value: bool | None
) -> None:
    original, reason = REFUSED[layout]
    path = write(tmp_path, original)
    with pytest.raises(ConfigTextEditError, match=f"(?i){reason}"):
        set_hold(path, None, "acp", value)
    assert path.read_bytes() == original.encode()
    assert [p.name for p in tmp_path.iterdir()] == ["abk.yaml"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only file")
def test_a_read_only_file_is_refused_and_left_as_it_was(tmp_path: Path) -> None:
    original = BLOCK
    path = write(tmp_path, original)
    path.chmod(0o444)
    with pytest.raises(ConfigTextEditError, match="(?i)read-only|writ|permission"):
        set_hold(path, None, "acp", True)
    assert path.read_bytes() == original.encode()
    assert [p.name for p in tmp_path.iterdir()] == ["abk.yaml"]


def test_a_file_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigTextEditError):
        set_hold(tmp_path / "abk.yaml", None, "acp", True)


# --- backup, reload check, mode ---


def test_the_original_is_copied_once_to_a_backup_beside_the_file(tmp_path: Path) -> None:
    original = HEAD + BLOCK + TAIL
    path = write(tmp_path, original)
    first = set_hold(path, None, "acp", True)
    assert first.backup == backup_of(path)
    assert backup_of(path).read_text() == original
    second = set_hold(path, None, "claude_code", True)
    assert second.changed
    assert second.backup is None
    set_hold(path, None, "rest", True)
    set_hold(path, None, "acp", None)
    assert backup_of(path).read_text() == original
    assert splits(path) == {
        "acp": {"marker": "runtime_acp"},
        "claude_code": {"marker": "runtime_claude_code", "hold": True},
        "rest": {"hold": True},
    }


def test_the_result_is_a_document_that_loads_with_the_expected_hold(tmp_path: Path) -> None:
    before = yaml.safe_load(HEAD + BLOCK + TAIL)
    path = write(tmp_path, HEAD + BLOCK + TAIL)
    set_hold(path, None, "acp", True)
    set_hold(path, None, "claude_code", None)
    after = loaded(path)
    assert after["tests"]["tier2_splits"] == {
        "acp": {"marker": "runtime_acp", "hold": True},
        "claude_code": {"marker": "runtime_claude_code"},
    }
    assert (after["planning"], after["repos"]) == (before["planning"], before["repos"])


# Layouts the line scan could take for something simple: the edit either gives the expected
# `hold` and leaves the marker as it was, or is refused with the file untouched.
TRICKY = {
    "brace in a quoted marker": 'tests:\n  tier2_splits:\n    acp: {marker: "a}b"}\n',
    "comma in a quoted marker": 'tests:\n  tier2_splits:\n    acp: {marker: "a, hold: false"}\n',
    "hash in a quoted marker": 'tests:\n  tier2_splits:\n    acp: {marker: "a #b"}\n',
    "keep-chomped scalar at the end": (
        "tests:\n  tier2_splits:\n    acp: {marker: m}\n  note: |+\n    text\n\n\nrepos: {}\n"
    ),
}


@pytest.mark.parametrize("layout", sorted(TRICKY))
def test_an_edit_is_written_only_when_it_reloads_to_the_expected_hold(
    tmp_path: Path, layout: str
) -> None:
    original = TRICKY[layout]
    path = write(tmp_path, original)
    marker = yaml.safe_load(original)["tests"]["tier2_splits"]["acp"]["marker"]
    try:
        set_hold(path, None, "acp", True)
    except ConfigTextEditError:
        assert path.read_bytes() == original.encode()
        assert [p.name for p in tmp_path.iterdir()] == ["abk.yaml"]
    else:
        assert splits(path)["acp"] == {"marker": marker, "hold": True}
        assert loaded(path)["tests"].get("note") == yaml.safe_load(original)["tests"].get("note")


def test_the_file_keeps_its_mode(tmp_path: Path) -> None:
    path = write(tmp_path, BLOCK)
    path.chmod(0o640)
    set_hold(path, None, "acp", True)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert splits(path)["acp"]["hold"] is True
