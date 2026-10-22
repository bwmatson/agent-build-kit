"""`abk tags` and `abk check` call a `Separate:` line in an `[e2e-test]` group redundant, with
the file and line, and say nothing of one in a `[unit-test]` group (spec: unit-joining). Neither
command changes its exit code for it."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan


def tasks(kind: str) -> str:
    return (
        f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [{kind}] Group 1\n\n"
        "Separate: reviewed and reverted on its own\n\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"
    )


def separate_line(text: str) -> int:
    return next(n for n, line in enumerate(text.splitlines(), start=1) if "Separate:" in line)


def warnings_of(out: str) -> list[str]:
    return [line for line in out.splitlines() if "warning: group" in line]


def test_tags_warns_of_a_separate_line_in_an_e2e_group_and_not_in_a_unit_test_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks("e2e-test"))
    run.write("plain", tasks("unit-test"))

    capsys.readouterr()
    live = cli.cmd_tags(argparse.Namespace(change="live", all=False), run.inst)
    live_out = capsys.readouterr().out
    plain = cli.cmd_tags(argparse.Namespace(change="plain", all=False), run.inst)
    plain_out = capsys.readouterr().out

    found = warnings_of(live_out)
    assert len(found) == 1, live_out
    assert f"tasks.md:line {separate_line(tasks('e2e-test'))}" in found[0]
    assert "group 1" in found[0] and "Separate" in found[0] and "redundant" in found[0]
    assert warnings_of(plain_out) == []
    assert (live, plain) == (0, 0)


def test_check_prints_the_same_warning_after_the_openspec_output_and_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks("e2e-test"))
    run.write("plain", tasks("unit-test"))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    capsys.readouterr()
    status = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1, out
    assert "live" in found[0] and "redundant" in found[0]
    assert out.index("all valid") < out.index(found[0])
