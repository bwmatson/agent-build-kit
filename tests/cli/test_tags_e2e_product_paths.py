"""`abk tags` and `abk check` warn, with the file and line, of a task in an `[e2e-test]` group that
names a path which is not a test path, a doc, the changelog or declared support, and say nothing
of the same text in a `[unit-test]` group; neither changes its exit code (spec: e2e-group-scope)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import OPT_OUT, Replan

SCOPE = "which is not a test path, a doc, the changelog or declared support"


def tasks(kind: str, *lines: str, support: str = "") -> str:
    body = "".join(f"- [ ] 1.{n} {line}\n" for n, line in enumerate(lines, start=1))
    return f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [{kind}] Group 1\n\n{support}\n{body}"


def warnings_of(out: str) -> list[str]:
    return [line for line in out.splitlines() if "warning: group" in line and "names" in line]


def tags(run: Replan, capsys: pytest.CaptureFixture[str], change: str) -> tuple[int, str]:
    capsys.readouterr()
    code = cli.cmd_tags(argparse.Namespace(change=change, all=False), run.inst)
    return code, capsys.readouterr().out


def test_a_product_path_in_an_e2e_group_draws_the_warning_with_file_and_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    text = tasks("e2e-test", "Test: the route.", "Fix the retry in `src/client/retry.py`")
    run.write("live", text)

    code, out = tags(run, capsys, "live")

    found = warnings_of(out)
    line = next(n for n, t in enumerate(text.splitlines(), start=1) if "retry.py" in t)
    assert code == 0
    assert len(found) == 1, out
    assert f"tasks.md:line {line}" in found[0]
    assert f"group 1: task 1.2 names src/client/retry.py, {SCOPE}" in found[0]


def test_test_doc_changelog_and_support_paths_draw_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "live",
        tasks(
            "e2e-test",
            "Test: `tests/e2e/test_route.py` streams.",
            "Document it in `docs/cli.md`.",
            "Note it in `CHANGELOG.md`.",
            "Start the stack with `compose.e2e.yml`.",
            "Fix `src/client/retry.py`.",
            support="Support: `compose.e2e.yml` — the live tests start the stack\n",
        ),
    )

    code, out = tags(run, capsys, "live")

    found = warnings_of(out)
    assert len(found) == 1, out
    assert "src/client/retry.py" in found[0]
    assert code == 0


def test_a_script_is_quiet_on_a_line_with_a_test_path_and_warned_on_a_line_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write(
        "live",
        tasks(
            "e2e-test",
            "Test: `tests/e2e/test_route.py` starts the stack with `scripts/seed-stack.sh`.",
            "Make `scripts/seed-stack.sh` seed two users.",
        ),
    )

    code, out = tags(run, capsys, "live")

    found = warnings_of(out)
    assert len(found) == 1, out
    assert "task 1.2 names scripts/seed-stack.sh" in found[0]
    assert code == 0


def test_a_path_named_twice_in_a_group_is_warned_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks("e2e-test", "Fix `src/a.py`.", "Fix `src/a.py` again."))

    _, out = tags(run, capsys, "live")

    assert len(warnings_of(out)) == 1, out


def test_the_same_text_in_a_unit_test_group_draws_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    live = tasks("e2e-test", "Fix `src/client/retry.py`.").replace("Group 1", "Group 2")
    live = live.replace("## 1.", "## 2.").replace("- [ ] 1.", "- [ ] 2.")
    plain = tasks("unit-test", "Test: it.", "Fix the retry in `src/client/retry.py`")
    run.write("mixed", plain + "\n" + live.split(OPT_OUT, 1)[1])

    code, out = tags(run, capsys, "mixed")

    found = warnings_of(out)
    assert len(found) == 1, out
    assert found[0].count("group 2") == 1 and "group 1" not in found[0]
    assert code == 0


def test_check_prints_the_warning_after_the_openspec_output_and_exits_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch)
    run.write("live", tasks("e2e-test", "Fix `src/client/retry.py`."))
    run.write("plain", tasks("unit-test", "Fix `src/client/retry.py`."))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    capsys.readouterr()
    status = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    found = warnings_of(out)
    assert status == 0
    assert len(found) == 1, out
    assert "live" in found[0] and "src/client/retry.py" in found[0]
    assert out.index("all valid") < out.index(found[0])
