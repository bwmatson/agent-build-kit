"""What `abk tags` and `abk check` say of a merge `Needs:` (spec: needs-can-wait-for-a-merge).

`Needs: <change> group <n> merged — why` is a dependency on the merge, accepted without a
warning. A plain `Needs:` to a group of another repository waits for the merge too, which the
author is told in an info note; a same-repo one is not. A merge line on the change's own group
stays an error.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import work_graph
from tests.cli.replan_driver import OPT_OUT, Replan

pytestmark = pytest.mark.usefixtures("scripted_engine")

IN_ANOTHER_REPO = "Needs: {change} group 1 is in another repository, so it waits for the merge"


def feature_md(*lines: str) -> str:
    text = f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] One\n\n- [ ] 1.1 Test: it.\n\n"
    text += "## 2. [app] [unit-test] Two\n\n"
    text += "".join(f"{line}\n" for line in lines)
    return text + "\n- [ ] 2.1 Test: it.\n- [ ] 2.2 Do it.\n"


def other_md(repo: str) -> str:
    return f"# Tasks\n\n{OPT_OUT}\n## 1. [{repo}] [unit-test] Base\n\n- [ ] 1.1 Test: it.\n"


def run_tags(inst: Installation) -> int:
    return cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)


def run_check(inst: Installation) -> int:
    return cli.cmd_check(argparse.Namespace(), inst)


@pytest.fixture(params=[run_tags, run_check], ids=["tags", "check"])
def command(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Callable[[Installation], int]:
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))
    return request.param


def test_the_deprecation_warning_function_is_gone() -> None:
    assert not hasattr(work_graph, "merged_needs_warnings")


def test_a_merge_line_prints_no_deprecation_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: Callable[[Installation], int],
) -> None:
    run = Replan(tmp_path, monkeypatch, base=other_md("app"))
    run.write("feature", feature_md("Needs: base group 1 merged — they edit one file"))
    capsys.readouterr()

    status = command(run.inst)

    seen = capsys.readouterr()
    assert status == 0, seen.out + seen.err
    assert "deprecated" not in (seen.out + seen.err).lower()


def test_a_merge_line_on_the_own_change_is_the_error_and_nothing_is_deprecated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = Replan(tmp_path, monkeypatch, base=other_md("app"))
    run.write(
        "feature",
        feature_md("Needs: feature group 1 merged — why", "Needs: base group 1 merged — why"),
    )
    capsys.readouterr()

    status = run_tags(run.inst)

    seen = capsys.readouterr()
    assert status == 1
    assert "own group" in seen.out + seen.err
    assert "deprecated" not in (seen.out + seen.err).lower()


def test_only_a_plain_needs_on_another_repository_gets_the_info_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: Callable[[Installation], int],
) -> None:
    run = Replan(tmp_path, monkeypatch, shared=other_md("platform"), base=other_md("app"))
    run.write(
        "feature",
        feature_md("Needs: shared group 1 — it adds the field", "Needs: base group 1 — why"),
    )
    capsys.readouterr()

    status = command(run.inst)

    seen = capsys.readouterr()
    output = seen.out + seen.err
    assert status == 0, output
    notes = [line for line in output.splitlines() if "another repository" in line]
    assert len(notes) == 1, output
    assert "tasks.md:line 11: info: group 2: " in notes[0]
    assert IN_ANOTHER_REPO.format(change="shared") in notes[0]
