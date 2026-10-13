"""The apply engine: merge the recommended policy into an agent's configuration over a
descriptor. Every test uses a scratch home and a neutral row; the engine never reads the
environment, and `resolve_home` is the one place a variable is looked at."""

from __future__ import annotations

import difflib
import json
import os
import stat
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from agent_build_kit.runtimes.known_agents import ApplyFormat, ApplyPolicy, Toolset, YamlVersion
from agent_build_kit.runtimes.policy_apply import (
    BACKUP_SUFFIX,
    ApplyRefused,
    Status,
    apply,
    resolve_home,
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


def _quoted(items: Sequence[str]) -> str:
    """A block list of double-quoted scalars (JSON strings are valid YAML ones)."""
    return "".join(f"    - {json.dumps(item)}\n" for item in items)


def _config(home: Path, text: str, descriptor: ApplyPolicy = FIRST) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / descriptor.file
    path.write_text(text)
    return path


def _deny(path: Path, keys: Sequence[str] = FIRST.deny_path) -> list[str]:
    value = yaml.safe_load(path.read_text())
    for key in keys:
        value = value[key]
    return value


def _added_lines(before: str, after: str) -> list[str]:
    return [
        line[2:]
        for line in difflib.ndiff(before.splitlines(), after.splitlines())
        if line.startswith("+ ")
    ]


def _removed_lines(before: str, after: str) -> list[str]:
    return [
        line
        for line in difflib.ndiff(before.splitlines(), after.splitlines())
        if line.startswith("- ")
    ]


def test_missing_patterns_follow_the_existing_entries_in_table_order(tmp_path: Path) -> None:
    recommended = patterns()
    held = [recommended[5], recommended[1]]
    wanted = ["mine one *", "mine two *", *held]
    path = _config(tmp_path / "home", "approvals:\n  deny:\n" + _quoted(wanted))

    result = apply(FIRST, tmp_path / "home")

    assert result.status == Status.WRITTEN
    assert _deny(path) == wanted + [p for p in recommended if p not in wanted]
    assert result.added == tuple(p for p in recommended if p not in wanted)


def test_a_list_written_as_one_string_keeps_it_as_the_first_item(tmp_path: Path) -> None:
    path = _config(tmp_path / "home", "approvals:\n  deny: 'rm -rf *'\n")

    apply(FIRST, tmp_path / "home")

    assert _deny(path) == ["rm -rf *", *patterns()]


def test_a_missing_section_and_list_are_created(tmp_path: Path) -> None:
    path = _config(tmp_path / "home", "model: fast\n")

    apply(FIRST, tmp_path / "home")

    assert _deny(path) == patterns()
    assert yaml.safe_load(path.read_text())["model"] == "fast"


def test_a_missing_list_in_an_existing_section_is_created(tmp_path: Path) -> None:
    path = _config(tmp_path / "home", "approvals:\n  mode: ask\n")

    apply(FIRST, tmp_path / "home")

    assert _deny(path) == patterns()
    assert yaml.safe_load(path.read_text())["approvals"]["mode"] == "ask"


COMMENTED = """\
# the operator's notes
model: "fast"   # quoted on purpose
approvals:
  mode: "off"   # keep quoted
  deny: ["mine one *"]   # inline list
platform:
  tools: [file]   # a flow list
# trailing comment
"""


def test_only_added_lines_differ_and_comments_and_other_keys_stay(tmp_path: Path) -> None:
    path = _config(tmp_path / "home", COMMENTED)

    apply(FIRST, tmp_path / "home")

    after = path.read_text()
    added = _added_lines(COMMENTED, after)
    assert added
    items = {*patterns(), *(json.dumps(p) for p in patterns()), '"mine one *"'}
    stray = [
        line
        for line in added
        if "deny" not in line and line.strip().removeprefix("- ") not in items
    ]
    assert stray == []
    assert after.split("approvals:")[0] == COMMENTED.split("approvals:")[0]
    for kept in (
        "# the operator's notes",
        "# quoted on purpose",
        "# keep quoted",
        "# trailing comment",
        "# a flow list",
    ):
        assert kept in after
    assert 'model: "fast"' in after
    assert 'mode: "off"' in after
    assert "tools: [file]" in after
    assert _deny(path)[0] == "mine one *"
    # What the inline list becomes is the writer's; no other line may be lost.
    assert [line for line in _removed_lines(COMMENTED, after) if "deny" not in line] == []


def test_a_second_run_reports_nothing_and_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = _config(home, "approvals:\n  deny: []\n")
    apply(FIRST, home)
    written = path.read_text()
    stamp = path.stat().st_mtime_ns

    again = apply(FIRST, home)

    assert again.status == Status.UNCHANGED
    assert again.added == ()
    assert again.backup is None
    assert path.read_text() == written
    assert path.stat().st_mtime_ns == stamp
    assert sorted(p.name for p in home.iterdir()) == sorted(
        [FIRST.file, FIRST.file + BACKUP_SUFFIX]
    )


def test_the_first_write_backs_up_the_original_and_a_later_write_keeps_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = _config(home, "# mine\napprovals:\n  deny: []\n")
    original = path.read_text()

    first = apply(FIRST, home)

    backup = home / (FIRST.file + BACKUP_SUFFIX)
    assert first.backup == backup
    assert backup.read_text() == original
    path.write_text(path.read_text() + "# a hand edit\n")

    later = apply(FIRST, home, extra=["one more *"])

    assert later.status == Status.WRITTEN
    assert later.backup is None
    assert backup.read_text() == original


def test_a_dry_run_shows_the_diff_and_writes_no_file_and_no_backup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = _config(home, "approvals:\n  deny: []\n")

    result = apply(FIRST, home, dry_run=True)

    assert result.status == Status.WOULD_WRITE
    assert result.diff
    assert path.read_text() == "approvals:\n  deny: []\n"
    assert [p.name for p in home.iterdir()] == [FIRST.file]


def test_a_file_that_does_not_parse_refuses_and_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    broken = "approvals: [unclosed\n  deny: {\n"
    path = _config(home, broken)

    with pytest.raises(ApplyRefused, match=FIRST.file):
        apply(FIRST, home)

    assert [p.name for p in home.iterdir()] == [FIRST.file]
    assert path.read_text() == broken


@pytest.mark.parametrize(
    "text",
    ["approvals:\n  deny: 5\n", "approvals: 3\n", "approvals:\n  - one\n"],
)
def test_a_wrong_shaped_value_refuses_naming_the_file_and_key_path(
    tmp_path: Path, text: str
) -> None:
    home = tmp_path / "home"
    path = _config(home, text)

    with pytest.raises(ApplyRefused) as refused:
        apply(FIRST, home)

    assert FIRST.file in str(refused.value)
    assert "approvals" in str(refused.value)
    assert path.read_text() == text
    assert [p.name for p in home.iterdir()] == [FIRST.file]


def test_a_number_list_names_the_whole_key_path(tmp_path: Path) -> None:
    _config(tmp_path / "home", "approvals:\n  deny: 5\n")

    with pytest.raises(ApplyRefused, match=r"approvals\.deny"):
        apply(FIRST, tmp_path / "home")


def test_an_absent_file_says_so_names_the_variable_and_creates_nothing(tmp_path: Path) -> None:
    home = tmp_path / "no-such-home"

    result = apply(FIRST, home)

    assert result.status == Status.ABSENT
    assert str(home / FIRST.file) in result.message
    assert FIRST.home_env in result.message
    assert not home.exists()
    assert list(tmp_path.iterdir()) == []


def test_an_absent_file_in_an_existing_home_is_not_created(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = apply(FIRST, home)

    assert result.status == Status.ABSENT
    assert list(home.iterdir()) == []


def test_the_write_goes_through_a_temporary_beside_the_file_and_keeps_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    path = _config(home, "approvals:\n  deny: []\n")
    path.chmod(0o640)
    moves: list[tuple[Path, Path]] = []
    real = os.replace

    def spy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        moves.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)

    apply(FIRST, home)

    sources = [src for src, dst in moves if dst == path]
    assert len(sources) == 1
    assert sources[0].parent == home
    assert sources[0] != path
    assert not sources[0].exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_a_write_that_fails_leaves_the_original_and_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    original = "approvals:\n  deny: []\n"
    path = _config(home, original)

    def fail(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr(os, "replace", fail)

    with pytest.raises((OSError, ApplyRefused)):
        apply(FIRST, home)

    assert path.read_text() == original
    assert {p.name for p in home.iterdir()} <= {FIRST.file, FIRST.file + BACKUP_SUFFIX}


def test_the_home_comes_from_the_descriptors_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    monkeypatch.setenv(FIRST.home_env, str(scratch))

    assert resolve_home(FIRST) == scratch


def test_the_home_falls_back_to_the_default_under_the_persons_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(FIRST.home_env, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "person"))

    assert resolve_home(FIRST) == tmp_path / "person" / FIRST.home_default


def test_a_run_reads_and_writes_only_the_resolved_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    person = tmp_path / "person"
    person.mkdir()
    (person / "keep.txt").write_text("mine")
    monkeypatch.setenv("HOME", str(person))
    scratch = tmp_path / "scratch"
    monkeypatch.setenv(FIRST.home_env, str(scratch))
    _config(scratch, "approvals:\n  deny: []\n")

    apply(FIRST, resolve_home(FIRST))

    assert [p.name for p in person.iterdir()] == ["keep.txt"]
    assert (person / "keep.txt").read_text() == "mine"
    assert sorted(p.name for p in scratch.iterdir()) == sorted(
        [FIRST.file, FIRST.file + BACKUP_SUFFIX]
    )


def test_a_second_row_runs_through_the_same_engine(tmp_path: Path) -> None:
    home = tmp_path / "other"
    path = _config(
        home,
        "# other agent\nversion: 1.2\ntools:\n  deny:\n" + _quoted(["mine *"]),
        SECOND,
    )

    result = apply(SECOND, home)

    assert result.status == Status.WRITTEN
    assert _deny(path, SECOND.deny_path) == ["mine *", *patterns()]
    assert "# other agent" in path.read_text()
    assert (home / (SECOND.file + BACKUP_SUFFIX)).exists()


def test_extras_are_merged_once_after_the_kits(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = _config(home, "model: fast\n")
    extra = ["site rule *", patterns()[0], "site rule *", "another *"]

    apply(FIRST, home, extra=extra)

    assert _deny(path) == patterns(extra=extra)
    assert _deny(path).count("site rule *") == 1


def test_a_toolset_replaces_the_list_only_when_asked_and_is_shown_from_to(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = _config(home, "platform:\n  tools: [web, file]\n")

    plain = apply(FIRST, home)
    assert plain.toolset_change is None
    assert yaml.safe_load(path.read_text())["platform"]["tools"] == ["web", "file"]

    asked = apply(FIRST, home, toolset=True)

    assert asked.toolset_change == (("web", "file"), ("file", "terminal"))
    assert yaml.safe_load(path.read_text())["platform"]["tools"] == ["file", "terminal"]


def test_a_dry_run_toolset_is_shown_and_not_written(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = _config(home, "platform:\n  tools: [web]\n")

    result = apply(FIRST, home, toolset=True, dry_run=True)

    assert result.toolset_change == (("web",), ("file", "terminal"))
    assert yaml.safe_load(path.read_text())["platform"]["tools"] == ["web"]


def test_a_row_without_a_toolset_refuses_the_request(tmp_path: Path) -> None:
    home = tmp_path / "other"
    path = _config(home, "tools:\n  deny: []\n", SECOND)

    with pytest.raises(ApplyRefused):
        apply(SECOND, home, toolset=True)

    assert path.read_text() == "tools:\n  deny: []\n"


@pytest.mark.parametrize("descriptor", [FIRST, SECOND], ids=["yaml-1.1", "yaml-1.2"])
def test_no_directive_or_document_start_is_written_that_the_file_lacked(
    tmp_path: Path, descriptor: ApplyPolicy
) -> None:
    keys = descriptor.deny_path
    before = f"# mine\n{keys[0]}:\n  {keys[1]}: []\n"
    path = _config(tmp_path / "home", before, descriptor)

    apply(descriptor, tmp_path / "home")

    after = path.read_text()
    assert "%YAML" not in after
    assert after.splitlines()[0] == "# mine"
    assert "---" not in after
    for line in _added_lines(before, after):
        assert line.strip().startswith("- ") or keys[1] in line
    assert all(keys[1] in line for line in _removed_lines(before, after))


def test_a_directive_the_file_had_is_kept_and_its_values_keep_their_spelling(
    tmp_path: Path,
) -> None:
    before = "%YAML 1.1\n---\napprovals:\n  mode: off\n  deny: []\n"
    path = _config(tmp_path / "home", before)

    apply(FIRST, tmp_path / "home")

    assert path.read_text().startswith("%YAML 1.1\n---\napprovals:\n  mode: off\n")


def test_bare_boolean_spellings_in_untouched_keys_and_entries_stay_as_written(
    tmp_path: Path,
) -> None:
    before = "approvals:\n  mode: off\n  deny:\n  - 'mine *'\nflag: on\nother: yes\n"
    path = _config(tmp_path / "home", before)

    apply(FIRST, tmp_path / "home")

    after = path.read_text()
    for kept in ("mode: off", "flag: on", "other: yes"):
        assert kept in (line.strip() for line in after.splitlines())
    assert _removed_lines(before, after) == []


def test_a_bare_boolean_entry_the_operator_wrote_stays_bare(tmp_path: Path) -> None:
    before = "approvals:\n  deny:\n  - yes\n"
    path = _config(tmp_path / "home", before)

    apply(FIRST, tmp_path / "home")

    assert "- yes" in (line.strip() for line in path.read_text().splitlines())
    assert _removed_lines(before, path.read_text()) == []


def test_a_section_present_but_empty_is_filled_like_a_missing_one(tmp_path: Path) -> None:
    path = _config(tmp_path / "home", "approvals:\nmodel: x\n")

    apply(FIRST, tmp_path / "home")

    loaded = yaml.safe_load(path.read_text())
    assert loaded["model"] == "x"
    assert loaded["approvals"]["deny"] == patterns()


def test_an_inline_deny_list_becomes_a_block_list_when_entries_are_added(
    tmp_path: Path,
) -> None:
    path = _config(tmp_path / "home", 'approvals:\n  deny: ["mine *"]\n')

    apply(FIRST, tmp_path / "home")

    assert _deny(path) == ["mine *", *patterns()]
    assert max(len(line) for line in path.read_text().splitlines()) < 200


def test_a_new_scalar_a_one_point_one_reader_would_misread_is_quoted(tmp_path: Path) -> None:
    path = _config(tmp_path / "home", "platform:\n  tools: [web]\n")

    apply(FIRST, tmp_path / "home", extra=["off"])

    assert '- "off"' in path.read_text()
