"""`abk e2e-test hold` and `release`: the configuration's `hold` and the state file written
together, both or neither (spec: e2e-runtime-blocks)."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.config import load
from agent_build_kit.pipeline.e2e_holds import HELD_FILE
from tests.cli.e2e_hold_fakes import (
    SPLITS,
    SPLITS_ACP_RELEASED,
    abk,
    gate_entry,
    held_entries,
    own_splits,
    planning,
)


def hold_of(config: Path, split: str) -> bool | None:
    return load(config).tests.e2e_splits[split].hold


def said(out: list[str], err: list[str]) -> str:
    return "\n".join([*out, *err])


def test_hold_sets_hold_true_in_the_text_and_writes_the_entry_in_one_operation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    before = config.read_text()

    code, out, err = abk(config, capsys, "e2e-test", "hold", "acp", "--reason", "out of budget")

    assert code == 0
    assert hold_of(config, "acp") is True
    assert config.read_text().replace("      hold: true\n", "") == before
    assert (config.parent / "abk.yaml.abk-backup").read_text() == before
    entry = held_entries(config)["acp"]
    assert entry["reason"] == "out of budget"
    assert entry["source"] == "command"
    assert entry["by"]
    assert entry.get("until") is None
    assert datetime.fromisoformat(entry["since"]).tzinfo is not None
    assert "acp" in said(out, err)


def test_hold_removes_a_hold_false_it_finds_on_the_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path, SPLITS_ACP_RELEASED)

    code, _, _ = abk(config, capsys, "e2e-test", "hold", "acp")

    assert code == 0
    assert hold_of(config, "acp") is True
    assert "hold: false" not in config.read_text()
    assert config.read_text().count("hold: true") == 1


def test_a_second_hold_updates_the_reason_and_keeps_one_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    assert abk(config, capsys, "e2e-test", "hold", "acp", "--reason", "first")[0] == 0

    code, _, _ = abk(config, capsys, "e2e-test", "hold", "acp", "--reason", "second")

    assert code == 0
    assert list(held_entries(config)) == ["acp"]
    assert held_entries(config)["acp"]["reason"] == "second"
    assert config.read_text().count("hold: true") == 1


def test_rest_can_be_held_and_its_entry_is_appended(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)

    code, _, _ = abk(config, capsys, "e2e-test", "hold", "rest")

    assert code == 0
    assert "rest: {hold: true}" in config.read_text()
    assert hold_of(config, "rest") is True
    assert "rest" in held_entries(config)


def test_hold_has_no_until_and_its_hold_stays_until_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)

    code, _, err = abk(config, capsys, "e2e-test", "hold", "acp", "--until", "2026-11-01")
    assert code == 2
    assert any("--until" in line for line in err)
    assert held_entries(config) == {}
    assert abk(config, capsys, "e2e-test", "hold", "acp")[0] == 0

    assert held_entries(config)["acp"].get("until") is None
    assert hold_of(config, "acp") is True


def test_release_removes_the_entry_and_the_hold_line_from_both_places(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    before = config.read_text()
    assert abk(config, capsys, "e2e-test", "hold", "acp")[0] == 0
    assert held_entries(config)

    code, out, err = abk(config, capsys, "e2e-test", "release", "acp")

    assert code == 0
    assert held_entries(config) == {}
    assert hold_of(config, "acp") is None
    assert config.read_text() == before
    assert "still held" not in said(out, err)


def test_release_says_when_a_gate_entry_still_holds_the_split_and_may_return(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    gate_entry(config, "acp", datetime.now(UTC) + timedelta(days=1))

    code, out, err = abk(config, capsys, "e2e-test", "release", "acp")

    assert code == 0
    assert "still held" in said(out, err)
    assert "gate" in said(out, err)
    assert "again" in said(out, err)


def test_a_name_nothing_declares_exits_2_naming_the_splits_there_are(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    assert abk(config, capsys, "e2e-test", "hold", "acp")[0] == 0
    before = config.read_text()

    for command in ("hold", "release"):
        code, out, err = abk(config, capsys, "e2e-test", command, "nothing")

        assert code == 2
        for name in ("acp", "claude_code", "rest"):
            assert name in said(out, err)
    assert config.read_text() == before


def test_releasing_a_split_that_is_not_held_says_so_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    before = config.read_text()

    code, out, err = abk(config, capsys, "e2e-test", "release", "acp")

    assert code == 0
    assert "not held" in said(out, err)
    assert config.read_text() == before
    assert not (config.parent / HELD_FILE).exists()
    assert not list(config.parent.glob("*.abk-backup"))


MULTI_LINE_FLOW = SPLITS.replace(
    "    acp:\n      marker: runtime_acp\n", "    acp: {\n      marker: runtime_acp\n    }\n"
)
ANCHORED = SPLITS.replace("    acp:\n", "    acp: &shared\n")


@pytest.mark.parametrize(
    ("tests", "reason"), [(MULTI_LINE_FLOW, "multi-line"), (ANCHORED, "anchor")]
)
@pytest.mark.parametrize("command", ["hold", "release"])
def test_a_configuration_that_cannot_be_edited_writes_nothing_and_says_what_to_do_by_hand(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tests: str,
    reason: str,
    command: str,
) -> None:
    config = planning(tmp_path, tests)
    before = config.read_text()
    gate_entry(config, "acp", datetime.now(UTC) + timedelta(days=1))
    state = (config.parent / HELD_FILE).read_text()

    code, out, err = abk(config, capsys, "e2e-test", command, "acp")

    assert code not in (0, 2)
    assert reason in said(out, err)
    assert "hold: true" in said(out, err)
    assert config.read_text() == before
    assert (config.parent / HELD_FILE).read_text() == state
    assert not list(config.parent.glob("*.abk-backup"))


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only file")
def test_an_unwritable_configuration_writes_neither_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)
    config.chmod(stat.S_IRUSR)

    code, out, err = abk(config, capsys, "e2e-test", "hold", "acp")

    assert code not in (0, 2)
    assert "hold: true" in said(out, err)
    assert not (config.parent / HELD_FILE).exists()
    assert "hold: true" not in config.read_text()


APP_RELEASED = own_splits("          hold: false\n")


def app_hold(config: Path, split: str = "acp") -> bool | None:
    own = load(config).repos["app"].tests.e2e_splits
    assert own is not None
    return own[split].hold


def test_hold_and_release_reach_a_repos_own_declaration_as_well_as_the_top_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path, app_tests=APP_RELEASED)
    before = config.read_text()

    assert abk(config, capsys, "e2e-test", "hold", "acp")[0] == 0

    assert hold_of(config, "acp") is True
    assert app_hold(config) is True
    assert "hold: false" not in config.read_text()

    code, _, _ = abk(config, capsys, "e2e-test", "release", "acp")

    assert code == 0
    assert held_entries(config) == {}
    assert config.read_text() == before.replace("          hold: false\n", "")


def test_a_split_declared_only_under_a_repo_can_be_held_and_released(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path, "", app_tests=own_splits(""))
    before = config.read_text()

    code, _, err = abk(config, capsys, "e2e-test", "hold", "acp")

    assert code == 0, err
    assert app_hold(config) is True
    assert "acp" in held_entries(config)

    assert abk(config, capsys, "e2e-test", "release", "acp")[0] == 0
    assert app_hold(config) is None
    assert held_entries(config) == {}
    assert config.read_text() == before


def test_a_refusal_at_one_place_writes_nothing_and_names_each_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    own = own_splits("").replace("        acp:\n", "        acp: &shared\n")
    config = planning(tmp_path, app_tests=own)
    before = config.read_text()

    code, out, err = abk(config, capsys, "e2e-test", "hold", "acp")

    assert code not in (0, 2)
    assert "repos.app.tests.e2e_splits" in said(out, err)
    assert config.read_text() == before
    assert not (config.parent / HELD_FILE).exists()
    assert not list(config.parent.glob("*.abk-backup"))


def test_release_puts_the_configuration_back_when_the_state_file_cannot_be_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    held = SPLITS.replace("marker: runtime_acp", "marker: runtime_acp\n      hold: true")
    config = planning(tmp_path, held)
    (config.parent / HELD_FILE).write_text("{not json")
    before = config.read_text()

    code, out, err = abk(config, capsys, "e2e-test", "release", "acp")

    assert code not in (0, 2)
    assert "nothing was released" in said(out, err)
    assert config.read_text() == before
    assert (config.parent / HELD_FILE).read_text() == "{not json"
    assert not list(config.parent.glob("*.abk-backup"))
