"""The e2e product-path warning reads paths through the shared group reader, which changes it on
purpose in two ways (spec: project-resolution): a glob is now seen by its literal prefix, and
text that is not a change (a `Verify:` segment, a sentence after "do not") stops voting. The
older behaviour is pinned in test_tags_e2e_product_paths.py, which these changes leave as it is."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan


def tasks(*lines: str) -> str:
    body = "".join(f"- [ ] 1.{n} {line}\n" for n, line in enumerate(lines, start=1))
    return f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [e2e-test] Group 1\n\n{body}"


def warnings_of(run: Replan, capsys: pytest.CaptureFixture[str], change: str) -> list[str]:
    capsys.readouterr()
    cli.cmd_tags(argparse.Namespace(change=change, all=False), run.inst)
    out = capsys.readouterr().out
    return [line for line in out.splitlines() if "warning: group" in line and "names" in line]


def test_changed_a_glob_in_an_e2e_group_is_seen_by_its_literal_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks("Test: the route.", "Rework everything under `src/client/**`."))

    found = warnings_of(run, capsys, "live")

    assert len(found) == 1, found
    assert "task 1.2 names src/client/," in found[0]


@pytest.mark.parametrize(
    "line",
    [
        "Test: the route. Verify: red against `src/client/retry.py`.",
        "Test: the route. Do not touch `src/client/retry.py`.",
    ],
)
def test_changed_text_that_is_not_a_change_stops_voting_in_an_e2e_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    line: str,
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks(line))

    assert warnings_of(run, capsys, "live") == []
