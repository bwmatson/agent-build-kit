"""`abk tags` and `abk check` warn, and do not fail, of a task in an `[e2e-test]` group that asks in
words for a change to the product, naming the task, the group and the two routes for a product
fault (spec: e2e-task-wording)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan

FIX_WORDING = (
    "Fix whatever the subprocess run shows that in-process calls could not (the entry point, "
    "the working directory, the default workspace path)."
)


def group(number: int, kind: str, *lines: str, support: str = "") -> str:
    body = "".join(f"- [ ] {number}.{n} {line}\n" for n, line in enumerate(lines, start=1))
    return f"## {number}. [app] [{kind}] Group {number}\n\n{support}\n{body}\n"


def tasks(*groups: str) -> str:
    return f"# Tasks\n\n{OPT_OUT}\n" + "".join(groups)


def wording_warnings(out: str) -> list[str]:
    return [line for line in out.splitlines() if "warning" in line and "product-defect" in line]


def tags(run: Replan, capsys: pytest.CaptureFixture[str], change: str) -> tuple[int, str]:
    capsys.readouterr()
    code = cli.cmd_tags(argparse.Namespace(change=change, all=False), run.inst)
    return code, capsys.readouterr().out


def test_a_fix_asked_for_in_words_is_warned_with_task_group_and_both_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks(group(1, "e2e-test", "Test: the run.", FIX_WORDING)))

    code, out = tags(run, capsys, "live")

    found = wording_warnings(out)
    assert code == 0
    assert len(found) == 1, out
    assert "group 1" in found[0] and "1.2" in found[0]
    assert "[unit-test]" in found[0] and "Needs:" in found[0]


@pytest.mark.parametrize(
    "verb",
    ["Fix", "Change", "Add", "Implement", "Update", "Refactor", "Remove", "Rename", "Make"],
)
def test_each_changing_verb_is_warned(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks(group(1, "e2e-test", f"{verb} the entry point so the run starts.")))

    code, out = tags(run, capsys, "live")

    assert code == 0
    assert len(wording_warnings(out)) == 1, out


def test_a_test_a_documentation_a_changelog_and_a_support_task_are_not_warned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "live",
        tasks(
            group(
                1,
                "e2e-test",
                "Test: fix is not needed when the run starts.",
                "Document the run in the architecture docs.",
                "Update the docs for the live run.",
                "Add a changelog line for the live run.",
                "Support: `compose.e2e.yml` — add the stack file the live tests start.",
                support="Support: `compose.e2e.yml` — the live tests start the stack\n",
            )
        ),
    )

    code, out = tags(run, capsys, "live")

    assert code == 0
    assert wording_warnings(out) == [], out


def test_a_changing_verb_task_that_names_a_test_or_support_path_is_not_warned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "live",
        tasks(
            group(
                1,
                "e2e-test",
                "Add `tests/test_run.py` for the live run.",
                "Add `compose.e2e.yml` for the stack.",
                support="Support: `compose.e2e.yml` — the live tests start the stack\n",
            )
        ),
    )

    code, out = tags(run, capsys, "live")

    assert code == 0
    assert wording_warnings(out) == [], out


def test_a_changing_verb_task_that_names_a_product_path_gets_only_the_path_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks(group(1, "e2e-test", "Fix `src/app/cli.py`.")))

    code, out = tags(run, capsys, "live")

    assert code == 0
    assert wording_warnings(out) == [], out
    assert "src/app/cli.py" in out


@pytest.mark.parametrize(
    "text",
    [
        "Fix: the entry point so the run starts.",
        "Update, then rerun the entry point.",
        "Fix the entry point and note it in the changelog.",
    ],
)
def test_punctuation_after_the_verb_and_a_late_documentation_word_are_still_warned(
    text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks(group(1, "e2e-test", text)))

    code, out = tags(run, capsys, "live")

    assert code == 0
    assert len(wording_warnings(out)) == 1, out


def test_the_same_words_in_a_unit_test_group_are_not_warned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("plain", tasks(group(1, "unit-test", "Test: it.", FIX_WORDING)))

    code, out = tags(run, capsys, "plain")

    assert code == 0
    assert wording_warnings(out) == [], out


def test_check_prints_the_warning_for_the_e2e_group_only_and_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks(group(1, "e2e-test", FIX_WORDING)))
    run.write("plain", tasks(group(1, "unit-test", FIX_WORDING)))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    capsys.readouterr()
    status = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    found = wording_warnings(out)
    assert status == 0
    assert len(found) == 1, out
    assert "live" in found[0] and "group 1" in found[0]
    assert out.index("all valid") < out.index(found[0])
