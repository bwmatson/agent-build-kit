"""`abk policy show` for an agent whose configuration the kit can read: what the recommendation
lacks there, what is the person's own, and the toolset, without writing or running anything."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.runtimes.recommended_policy import RECOMMENDED, patterns
from tests.cli.policy_apply_fakes import (
    AGENT,
    BARE,
    CURRENT_TOOLSET,
    DESCRIPTOR,
    OWN,
    Home,
    installation,
    run_apply,
)


def show(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    config: Path,
    home: Home,
) -> tuple[int, str, str]:
    """The exit code, the output, and the part of it that comes after the configuration's path."""
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("a program was started"))
    code, terminal = run_apply(capsys, monkeypatch, config, home, command="show")
    assert terminal.asked == 0
    out = terminal.out
    assert str(home.config) in out
    return code, out, out[out.index(str(home.config)) :]


def without_class(label: str) -> list[str]:
    """The recommended patterns but those only `label` supplies."""
    others = {glob for policy in RECOMMENDED if policy.label != label for glob in policy.globs}
    return [glob for glob in patterns() if glob in others]


def test_the_missing_patterns_are_named_by_class_and_the_complete_classes_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, runtime = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv))
    home = Home(tmp_path, monkeypatch)
    missing = next(policy for policy in RECOMMENDED if policy.globs)
    kept = without_class(missing.label)
    home.holds([*OWN, *kept], CURRENT_TOOLSET)
    before = home.config.read_text()

    code, _, tail = show(capsys, monkeypatch, config, home)

    assert code == 0
    assert missing.label in tail
    complete = [
        policy.label
        for policy in RECOMMENDED
        if policy.globs and all(glob in kept for glob in policy.globs)
    ]
    assert complete
    for label in complete:
        assert label not in tail
    assert home.config.read_text() == before
    assert home.files() == [home.config.name]
    assert runtime.checked == []


def test_the_persons_own_entries_are_counted_and_not_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv))
    home = Home(tmp_path, monkeypatch)
    home.holds([*OWN, *patterns()], CURRENT_TOOLSET)

    code, _, tail = show(capsys, monkeypatch, config, home)

    assert code == 0
    for entry in OWN:
        assert entry not in tail
    assert [line for line in tail.splitlines() if re.search(rf"\b{len(OWN)}\b", line)]


def test_the_toolset_recommendation_is_shown_against_the_current_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert DESCRIPTOR.toolset is not None
    config, _ = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv))
    home = Home(tmp_path, monkeypatch)
    home.holds(OWN, CURRENT_TOOLSET)

    code, _, tail = show(capsys, monkeypatch, config, home)

    assert code == 0
    for name in (*CURRENT_TOOLSET, *DESCRIPTOR.toolset.names):
        assert name in tail
    assert "--toolset" in tail


def test_an_absent_configuration_is_said_to_be_so_and_the_recommendation_is_still_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv))
    home = Home(tmp_path, monkeypatch)

    code, out, tail = show(capsys, monkeypatch, config, home)

    assert code == 0
    assert any(word in tail.lower() for word in ("no configuration", "not found", "absent"))
    for policy in RECOMMENDED:
        assert policy.label in out
    assert home.files() == []


def test_an_unparseable_configuration_is_said_to_be_so_and_the_recommendation_is_still_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, _ = installation(tmp_path, monkeypatch, command=list(AGENT.variants[0].argv))
    home = Home(tmp_path, monkeypatch)
    broken = "approvals: [unclosed\n  deny: -\n"
    home.write(broken)

    code, out, tail = show(capsys, monkeypatch, config, home)

    assert code == 0
    assert "parse" in tail.lower()
    for policy in RECOMMENDED:
        assert policy.label in out
    assert home.config.read_text() == broken
    assert home.files() == [home.config.name]


def test_an_agent_with_no_applier_is_one_the_kit_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, runtime = installation(tmp_path, monkeypatch, command=list(BARE.variants[0].argv))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("a program was started"))

    code, terminal = run_apply(capsys, monkeypatch, config, None, command="show")

    assert code == 0
    assert "cannot read" in terminal.out.lower()
    assert "abk policy patterns" in terminal.out
    for policy in RECOMMENDED:
        assert policy.label in terminal.out
    assert runtime.checked == []
