"""The apply engine writes by inserting lines into the original text: every other byte of the
operator's file is as it was, what it cannot insert it refuses, and the result is parsed back
before it is written."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from agent_build_kit.runtimes.known_agents import ApplyFormat, ApplyPolicy, Toolset, YamlVersion
from agent_build_kit.runtimes.policy_apply import (
    BACKUP_SUFFIX,
    ApplyRefused,
    Status,
    apply,
)
from agent_build_kit.runtimes.recommended_policy import patterns

FIRST = ApplyPolicy(
    home_env="NEUTRAL_AGENT_HOME",
    home_default=".neutral-agent",
    file="config.yaml",
    format=ApplyFormat.YAML,
    deny_path=("approvals", "deny"),
    yaml_version=YamlVersion.V1_1,
    toolset=Toolset(path=("platform", "tools"), names=("file", "terminal")),
    verified="fixture",
)
SECOND = ApplyPolicy(
    home_env="OTHER_AGENT_HOME",
    home_default=".other-agent",
    file="settings.yml",
    format=ApplyFormat.YAML,
    deny_path=("tools", "deny"),
    yaml_version=YamlVersion.V1_2,
    verified="fixture",
)
LISTED = "approvals:\n  deny:\n    - 'mine *'\n"


def _config(home: Path, text: str, descriptor: ApplyPolicy = FIRST) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / descriptor.file
    path.write_bytes(text.encode())
    return path


def _read(path: Path) -> str:
    return path.read_bytes().decode()


def _value(text: str, keys: tuple[str, ...]) -> object:
    found: object = yaml.safe_load(text)
    for key in keys:
        found = found[key] if isinstance(found, dict) and key in found else None
    return found


def _problems(before: str, after: str, descriptor: ApplyPolicy = FIRST) -> list[str]:
    """What a merge owes: no line of `before` changed, removed or moved (every one appears in
    `after`, in order), and the result is the original with the missing patterns added."""
    problems = []
    wanted = iter(after.splitlines())
    if not all(line in wanted for line in before.splitlines()):
        problems.append("a line of the original is missing, changed or out of order")
    held = _value(before, descriptor.deny_path)
    held_list = list(held) if isinstance(held, list) else []
    expected = [*held_list, *[p for p in patterns() if p not in held_list]]
    if _value(after, descriptor.deny_path) != expected:
        problems.append("the deny list is not the original plus the missing patterns")
    return problems


UNTOUCHED = {
    "null spellings": "k: ~\nn: null\n" + LISTED,
    "a capitalised boolean": "k: True\n" + LISTED,
    "spacing before a value": "key:    value    # c\n" + LISTED,
    "a multi-line plain scalar": "note: this is a long\n  plain scalar\n" + LISTED,
    "mixed indentation, list last": "a:\n    b: 1\n" + LISTED + "lst:\n- q\n",
    "mixed indentation, list first": (
        "approvals:\n  deny:\n  - a\nmodel:\n    name: x\n    list:\n        - y\n"
    ),
    "a trailing document end": LISTED + "...\n",
    "a directive and a document start": "%YAML 1.1\n---\n" + LISTED,
    "bare off, on and yes": "mode: off\nflag: on\nother: yes\n" + LISTED,
    "a list indented unlike its neighbours": ("approvals:\n  mode: x\n  deny:\n      - 'mine *'\n"),
    "comments between and after the items": (
        "approvals:\n  deny:\n    - 'a'\n    # between\n    - 'b'\n    # after\nmodel: x\n"
    ),
    "a quoted scalar": "title: \"he said 'hi'\"\n" + LISTED,
    "a last item with a comment": ("approvals:\n  deny:\n    - 'a'\n    - 'b'  # why\nmodel: x\n"),
    "no final newline": "approvals:\n  deny:\n    - 'mine *'",
    "a multi-line last item": (
        "approvals:\n  deny:\n    - 'a'\n    - 'multi\n      line'\nmodel: x\n"
    ),
    "an empty key": "approvals:\n  deny:\nmodel: x\n",
    "an empty key with a comment": "approvals:\n  deny:  # none yet\nmodel: x\n",
    "a missing list": "approvals:\n  mode: ask\nmodel: x\n",
    "a missing section": "model: x\n",
}


@pytest.mark.parametrize("text", UNTOUCHED.values(), ids=UNTOUCHED.keys())
def test_a_merge_only_adds_lines_and_a_second_run_changes_nothing(
    tmp_path: Path, text: str
) -> None:
    home = tmp_path / "home"
    path = _config(home, text)

    first = apply(FIRST, home)

    after = _read(path)
    assert first.status == Status.WRITTEN
    assert _problems(text, after) == []
    stamp = path.stat().st_mtime_ns

    again = apply(FIRST, home)

    assert again.status == Status.UNCHANGED
    assert again.backup is None
    assert _read(path) == after
    assert path.stat().st_mtime_ns == stamp
    assert _read(home / (FIRST.file + BACKUP_SUFFIX)) == text


def test_crlf_files_get_crlf_lines_and_keep_theirs(tmp_path: Path) -> None:
    text = "approvals:\r\n  deny:\r\n    - 'mine *'\r\nmodel: x\r\n"
    path = _config(tmp_path / "home", text)

    apply(FIRST, tmp_path / "home")

    after = _read(path)
    assert after.startswith("approvals:\r\n  deny:\r\n    - 'mine *'\r\n")
    assert after.count("\n") == after.count("\r\n")
    assert _problems(text.replace("\r\n", "\n"), after.replace("\r\n", "\n")) == []


@pytest.mark.parametrize(
    ("quote", "shown"),
    [("'", "    - 'gh pr merge'"), ('"', '    - "gh pr merge"'), ("", "    - gh pr merge")],
    ids=["single", "double", "plain"],
)
def test_new_items_copy_the_style_of_the_last_one(tmp_path: Path, quote: str, shown: str) -> None:
    path = _config(tmp_path / "home", f"approvals:\n  deny:\n    - {quote}mine{quote}\n")

    apply(FIRST, tmp_path / "home")

    assert shown in _read(path).splitlines()
    assert _value(_read(path), FIRST.deny_path) == ["mine", *patterns()]


def test_a_pattern_that_is_not_plain_safe_is_single_quoted_in_a_plain_list(
    tmp_path: Path,
) -> None:
    path = _config(tmp_path / "home", "approvals:\n  deny:\n    - mine\n")
    awkward = ["* starred", "key: value", "tail #note"]

    apply(FIRST, tmp_path / "home", extra=awkward)

    lines = _read(path).splitlines()
    for item in awkward:
        assert "    - '" + item.replace("'", "''") + "'" in lines
    assert _value(_read(path), FIRST.deny_path) == ["mine", *patterns(extra=awkward)]


def test_a_word_a_one_point_one_reader_misreads_is_quoted_and_a_one_point_two_one_is_not(
    tmp_path: Path,
) -> None:
    first = _config(tmp_path / "one", "approvals:\n  deny:\n    - mine\n")
    second = _config(tmp_path / "two", "tools:\n  deny:\n    - mine\n", SECOND)

    apply(FIRST, tmp_path / "one", extra=["off"])
    apply(SECOND, tmp_path / "two", extra=["off"])

    assert "    - 'off'" in _read(first).splitlines()
    assert "    - off" in _read(second).splitlines()


def test_a_list_missing_under_a_mapping_lands_after_its_last_entry_at_its_siblings_column(
    tmp_path: Path,
) -> None:
    text = "approvals:\n    mode: ask\n    other: 1  # c\n# note\nmodel: x\n"
    path = _config(tmp_path / "home", text)

    apply(FIRST, tmp_path / "home")

    lines = _read(path).splitlines()
    assert lines[:3] == text.splitlines()[:3]
    assert lines[3] == "    deny:"
    assert lines[4].startswith("        - '")
    assert lines[-2:] == ["# note", "model: x"]
    assert _problems(text, _read(path)) == []


def test_a_list_under_a_key_with_no_value_lands_right_under_it_one_step_deeper(
    tmp_path: Path,
) -> None:
    text = "approvals:\n    # a note\nmodel: x\n"
    path = _config(tmp_path / "home", text)

    apply(FIRST, tmp_path / "home")

    lines = _read(path).splitlines()
    assert lines[:3] == ["approvals:", "    # a note", "  deny:"]
    assert lines[3].startswith("    - '")
    assert _problems(text, _read(path)) == []


def test_a_missing_section_goes_at_the_end_of_the_mapping_before_a_trailing_document_end(
    tmp_path: Path,
) -> None:
    text = "model: x\n# the end\n...\n"
    path = _config(tmp_path / "home", text)

    apply(FIRST, tmp_path / "home")

    lines = _read(path).splitlines()
    assert lines[:2] == ["model: x", "approvals:"]
    assert lines[-2:] == ["# the end", "..."]
    assert _problems(text, _read(path)) == []


@pytest.mark.parametrize(
    "text", ["", "# only a comment\n", "---\n"], ids=["empty", "comment", "start"]
)
def test_an_empty_file_and_one_with_only_comments_take_the_block(tmp_path: Path, text: str) -> None:
    path = _config(tmp_path / "home", text)

    apply(FIRST, tmp_path / "home")

    after = _read(path)
    assert after.startswith(text)
    assert after[len(text) :].startswith("approvals:\n  deny:\n    - '")
    assert _value(after, FIRST.deny_path) == patterns()


def test_a_deeper_key_path_creates_each_missing_level(tmp_path: Path) -> None:
    text = "model: x\ntools:\nother: 1\n"
    path = _config(tmp_path / "home", text, SECOND)
    fresh = _config(tmp_path / "fresh", "model: x\n", SECOND)

    apply(SECOND, tmp_path / "home")
    apply(SECOND, tmp_path / "fresh")

    assert _read(path).splitlines()[:3] == ["model: x", "tools:", "  deny:"]
    assert _read(fresh).splitlines()[:3] == ["model: x", "tools:", "  deny:"]
    assert _problems(text, _read(path), SECOND) == []
    assert _value(_read(fresh), SECOND.deny_path) == patterns()


REFUSED = {
    "an inline list": ("approvals:\n  deny: [a, b]\n", "approvals.deny", "flow list"),
    "an empty inline list": ("approvals:\n  deny: []\n", "approvals.deny", "flow list"),
    "a quoted string": ('approvals:\n  deny: "mine *"\n', "approvals.deny", "single value"),
    "a plain string": ("approvals:\n  deny: mine\n", "approvals.deny", "single value"),
    "a tilde": ("approvals:\n  deny: ~\n", "approvals.deny", "null"),
    "null": ("approvals:\n  deny: null\n", "approvals.deny", "null"),
    "an alias": ("base: &x\n  - a\napprovals:\n  deny: *x\n", "approvals.deny", "alias"),
    "an anchored list": ("approvals:\n  deny: &x\n    - a\n", "approvals.deny", "anchored"),
    "a tagged list": ("approvals:\n  deny: !!seq\n    - a\n", "approvals.deny", "tagged"),
    "a flow mapping section": ("approvals: {deny: []}\n", "approvals", "flow mapping"),
    "a flow mapping top level": ("{approvals: {}}\n", FIRST.file, "flow mapping"),
    "several documents": (LISTED + "---\nb: 1\n", FIRST.file, "2 YAML documents"),
    "a top-level list": ("- a\n- b\n", FIRST.file, "not a mapping"),
}


@pytest.mark.parametrize(("text", "named", "reason"), REFUSED.values(), ids=REFUSED.keys())
def test_what_cannot_be_inserted_is_refused_naming_the_file_key_and_reason(
    tmp_path: Path, text: str, named: str, reason: str
) -> None:
    home = tmp_path / "home"
    path = _config(home, text)

    with pytest.raises(ApplyRefused) as refused:
        apply(FIRST, home)

    assert FIRST.file in str(refused.value)
    assert named in str(refused.value)
    assert reason in str(refused.value)
    assert _read(path) == text
    assert [p.name for p in home.iterdir()] == [FIRST.file]


def test_a_dry_run_refuses_the_same_way(tmp_path: Path) -> None:
    _config(tmp_path / "home", "approvals:\n  deny: [a]\n")

    with pytest.raises(ApplyRefused, match=r"approvals\.deny"):
        apply(FIRST, tmp_path / "home", dry_run=True)


def test_a_splice_that_does_not_parse_back_to_the_original_plus_the_entries_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    text = "model: x\n" + LISTED
    path = _config(home, text)
    real = YAML.load_all
    calls: list[str] = []

    def faulty(self: YAML, stream: str) -> Iterator[object]:
        calls.append(stream)
        if len(calls) <= 2:  # the engine's own reads of the original
            return real(self, stream)
        return iter([CommentedMap()])  # the read of the spliced text

    monkeypatch.setattr(YAML, "load_all", faulty)

    with pytest.raises(ApplyRefused, match="nothing was written"):
        apply(FIRST, home)

    assert _read(path) == text
    assert [p.name for p in home.iterdir()] == [FIRST.file]


def test_a_toolset_over_a_flow_list_changes_only_that_line(tmp_path: Path) -> None:
    text = "platform:\n  tools: [web, file]  # keep\nmodel: x\n" + LISTED
    path = _config(tmp_path / "home", text)
    apply(FIRST, tmp_path / "home")
    settled = _read(path)

    result = apply(FIRST, tmp_path / "home", toolset=True)

    after = _read(path)
    assert result.toolset_change == (("web", "file"), ("file", "terminal"))
    assert "  tools: [file, terminal]  # keep" in after.splitlines()
    assert [line for line in settled.splitlines() if line not in after.splitlines()] == [
        "  tools: [web, file]  # keep"
    ]
    assert len(after.splitlines()) == len(settled.splitlines())


def test_a_toolset_over_a_block_list_replaces_only_that_lists_lines(tmp_path: Path) -> None:
    text = "platform:\n  tools:\n    - web\n    # gone\n    - file\nmodel: x\n"
    path = _config(tmp_path / "home", text)

    apply(FIRST, tmp_path / "home", toolset=True)

    lines = _read(path).splitlines()
    assert lines[:5] == ["platform:", "  tools:", "    - file", "    - terminal", "model: x"]


def test_a_toolset_that_is_missing_is_inserted_as_a_block(tmp_path: Path) -> None:
    path = _config(tmp_path / "home", "model: x\n")

    result = apply(FIRST, tmp_path / "home", toolset=True)

    after = _read(path)
    assert result.toolset_change == ((), ("file", "terminal"))
    assert _value(after, ("platform", "tools")) == ["file", "terminal"]
    assert _value(after, FIRST.deny_path) == patterns()
    assert after.startswith("model: x\n")


def test_a_toolset_that_is_a_string_is_refused(tmp_path: Path) -> None:
    text = "platform:\n  tools: web\n"
    path = _config(tmp_path / "home", text)

    with pytest.raises(ApplyRefused, match=r"platform\.tools"):
        apply(FIRST, tmp_path / "home", toolset=True)

    assert _read(path) == text
