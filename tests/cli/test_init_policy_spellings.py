"""`abk init` prints the unrefused spelling the way `abk doctor` does, and asks before the fix."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.init.detect import Host
from tests.cli.test_init import fake_claude, fake_openspec, init_args
from tests.factories import git, init_repo, recognised_planning
from tests.runtimes.selectable import (
    AMEND,
    AMEND_REFUSED,
    AMEND_UNREFUSED,
    SelectableRuntime,
    select,
    spelling_report,
)


@pytest.fixture(autouse=True)
def stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_cmd, "run_openspec", fake_openspec)
    monkeypatch.setattr(init_cmd, "run_claude", fake_claude)
    monkeypatch.setattr(init_cmd, "host", lambda: Host.OTHER)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.t")


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "code")
    return repo


def test_an_unrefused_spelling_is_printed_by_class_and_spelling_and_the_fix_asked_first(
    tmp_path: Path,
    app: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    planning = recognised_planning(tmp_path / "planning")
    assert main([*init_args(planning, app), "--yes"]) == 0
    with (planning / "abk.yaml").open("a") as config:
        config.write(
            "runtime: loose\nruntimes:\n  loose:\n"
            "    policy_fix: [scripts/constrain-agent.sh, --strict]\n"
        )
    runtime = select(
        monkeypatch, SelectableRuntime("loose", reports=(spelling_report(), spelling_report()))
    )
    capsys.readouterr()
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(capsys.readouterr().out)
        runtime.log.append("ask")
        return "y"

    def run_fix(argv, **kwargs):
        runtime.log.append("fix")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(init_cmd, "ask", ask)
    monkeypatch.setattr(init_cmd, "run_fix", run_fix)

    main(init_args(planning, app))

    # What was printed when the operator was asked: the class, the spelling
    # that got through, and the class's other spellings as refused.
    assert len(asked) == 1
    for text in (AMEND, AMEND_UNREFUSED, *AMEND_REFUSED):
        assert text in asked[0]
    assert runtime.log == ["check", "ask", "fix", "check"]
