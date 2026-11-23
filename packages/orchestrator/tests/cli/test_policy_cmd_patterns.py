"""`abk policy patterns`: the recommended globs, in three formats, without an installation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.runtimes.recommended_policy import RECOMMENDED, patterns

EXTRAS = ["git * push --mirror*", "git push origin 'HEAD:main'"]


def run(
    capsys: pytest.CaptureFixture[str], *argv: str, config: Path | None = None
) -> tuple[int, str, str]:
    prefix = ["--config", str(config)] if config else []
    code = main([*prefix, "policy", "patterns", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def installation_with(tmp_path: Path, extras: list[str]) -> Path:
    path = tmp_path / "planning" / "abk.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump({"runtimes": {"claude_code": {"policy_extra": extras}}}))
    return path


@pytest.fixture
def outside_any_installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("ABK_CONFIG", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    return empty


def test_every_glob_is_printed_one_per_line_in_table_order_and_nothing_is_written(
    capsys: pytest.CaptureFixture[str], outside_any_installation: Path
) -> None:
    code, out, _ = run(capsys)

    assert code == 0
    assert out.splitlines() == patterns()
    assert list(outside_any_installation.iterdir()) == []


@pytest.mark.parametrize(("fmt", "load"), [("json", json.loads), ("yaml-list", yaml.safe_load)])
def test_a_structured_format_loads_back_to_the_same_list(
    fmt: str, load, capsys: pytest.CaptureFixture[str], outside_any_installation: Path
) -> None:
    code, out, _ = run(capsys, "--format", fmt)

    assert code == 0
    assert load(out) == patterns()
    # the list holds patterns with quotes, brackets, colons and `*`, so the round trip is a test
    for needle in ("'", "[", ":", "*"):
        assert any(needle in p for p in patterns())


def test_a_class_filter_prints_only_those_globs_in_table_order(
    capsys: pytest.CaptureFixture[str], outside_any_installation: Path
) -> None:
    first, second = RECOMMENDED[0], RECOMMENDED[4]

    code, out, _ = run(capsys, "--class", second.label, "--class", first.label)

    assert code == 0
    assert out.splitlines() == list(dict.fromkeys([*first.globs, *second.globs]))


def test_an_unknown_class_exits_two_naming_the_classes_there_are(
    capsys: pytest.CaptureFixture[str], outside_any_installation: Path
) -> None:
    code, out, err = run(capsys, "--class", "not a class")

    assert code == 2
    assert out == ""
    for policy in RECOMMENDED:
        assert policy.label in err


def test_extras_follow_the_kits_list_without_a_duplicate_when_asked_for(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = installation_with(tmp_path, [*EXTRAS, patterns()[0]])

    code, out, _ = run(capsys, "--extra", config=config)

    assert code == 0
    assert out.splitlines() == patterns(EXTRAS)


def test_without_asking_the_kits_list_is_printed_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = installation_with(tmp_path, EXTRAS)

    code, out, _ = run(capsys, config=config)

    assert code == 0
    assert out.splitlines() == patterns()


def test_extra_without_an_installation_exits_two_and_prints_no_globs(
    capsys: pytest.CaptureFixture[str], outside_any_installation: Path
) -> None:
    code, out, err = run(capsys, "--extra")

    assert code == 2
    assert out == ""
    assert "--extra" in err


def test_extra_with_an_installation_that_does_not_load_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = installation_with(tmp_path, ["git * push --mirror*", " "])

    code, out, err = run(capsys, "--extra", config=config)

    assert code == 2
    assert out == ""
    assert "--extra" in err


def test_a_class_with_no_globs_prints_an_empty_list_in_every_format(
    capsys: pytest.CaptureFixture[str], outside_any_installation: Path
) -> None:
    covered = next(p for p in RECOMMENDED if p.covered_by)
    assert covered.covered_by is not None

    for fmt in ("glob", "json", "yaml-list"):
        code, out, err = run(capsys, "--format", fmt, "--class", covered.label)

        assert code == 0
        assert covered.covered_by in err
        if fmt == "glob":
            assert out == ""
        else:
            assert (json.loads if fmt == "json" else yaml.safe_load)(out) == []


def test_extra_that_does_not_load_shows_which_key_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = installation_with(tmp_path, [" "])

    _, _, err = run(capsys, "--extra", config=config)

    assert "policy_extra" in err
