"""`abk init` and `abk install-skills` end to end, with the CLI, the model
and the terminal replaced."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import __version__, openspec
from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.config import load
from tests.factories import git, init_repo

STOCK_CONFIG = "schema: spec-driven\n"


def fake_openspec(argv, *, cwd, **kwargs):
    args = argv[len(openspec.command()) :]
    if args[0] == "init":
        (cwd / "openspec" / "changes" / "archive").mkdir(parents=True)
        (cwd / "openspec" / "specs").mkdir()
        (cwd / "openspec" / "config.yaml").write_text(STOCK_CONFIG)
        return subprocess.CompletedProcess(argv, 0, "", "")
    if args[0] == "validate":
        changes = sorted(p.name for p in (cwd / "openspec" / "changes").iterdir() if p.is_dir())
        items = [{"id": n, "type": "change", "valid": True, "issues": []} for n in changes]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"items": items}), "")
    return subprocess.CompletedProcess(argv, 0, f"ran {' '.join(args)}", "")


def write_change(planning: Path, change: str, repo: str) -> None:
    root = planning / "openspec" / "changes" / change
    root.mkdir(parents=True, exist_ok=True)
    (root / "proposal.md").write_text("## Why\n\nBecause.\n")
    (root / "tasks.md").write_text(
        f"## 1. [{repo}] [tier1] First\n\n- [ ] 1.1 Test it\n\n"
        "Acceptance: none — scaffolding only\n"
    )


def fake_claude(argv, *, cwd=None):
    """Research returns a document; propose writes the change its prompt names."""
    prompt = argv[2]
    if "openspec/changes/" not in prompt:
        return "## Formatting\n\n- rule\n\n## Sources\n\n- https://example.invalid\n"
    change = prompt.split("openspec/changes/", 1)[1].split("/", 1)[0]
    repo = change.rsplit("-code-standards", 1)[0].rsplit("-testing-infrastructure", 1)[0]
    assert cwd is not None
    write_change(cwd, change, repo)
    return ""


@pytest.fixture(autouse=True)
def stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_cmd, "run_openspec", fake_openspec)
    monkeypatch.setattr(init_cmd, "run_claude", fake_claude)
    monkeypatch.setattr(init_cmd, "ask", lambda prompt: pytest.fail("prompted unexpectedly"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.t")


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "code")
    return repo


@pytest.fixture
def platform(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "platform")
    git(repo, "remote", "add", "origin", "git@github.com:example/platform.git")
    (repo / "pyproject.toml").write_text('[project]\nname = "platform"\n')
    return repo


def test_init_lays_out_researches_proposes_and_commits(
    tmp_path: Path, app: Path, platform: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = tmp_path / "planning"

    code = main(["init", str(planning), "--repo", str(app), "--repo", str(platform), "--yes"])

    assert code == 0
    config = load(planning / "abk.yaml")
    assert set(config.repos) == {"app", "platform"}
    assert (planning / "docs" / "recommendations" / "python.md").exists()
    changes = sorted(p.name for p in (planning / "openspec" / "changes").iterdir() if p.is_dir())
    # app has code: both changes; platform is empty: standards only.
    assert changes == [
        "app-code-standards",
        "app-testing-infrastructure",
        "archive",
        "platform-code-standards",
    ]
    log = git(planning, "log", "--oneline")
    assert "abk init: workspace" in log
    assert git(planning, "status", "--porcelain") == ""
    out = capsys.readouterr().out
    assert "Next steps" in out
    assert "abk doctor" in out


def test_consumes_override_and_dry_run(tmp_path: Path, app: Path, platform: Path, capsys) -> None:
    planning = tmp_path / "planning"

    code = main(
        [
            "init",
            str(planning),
            "--repo",
            str(app),
            "--repo",
            str(platform),
            "--consumes",
            "app:platform",
            "--yes",
            "--dry-run",
        ]
    )

    assert code == 0
    assert not planning.exists()
    out = capsys.readouterr().out
    assert "consumes:" in out and "- platform" in out
    assert "propose: openspec/changes/app-testing-infrastructure/" in out
    assert "research: docs/recommendations/python.md (built-in seed)" in out


def test_skips_and_a_dirty_tree_are_not_committed(tmp_path: Path, app: Path) -> None:
    planning = init_repo(tmp_path / "planning")
    (planning / "notes.md").write_text("wip\n")

    code = main(
        ["init", str(planning), "--repo", str(app), "--yes", "--skip-research", "--skip-propose"]
    )

    assert code == 0
    assert not (planning / "docs" / "recommendations").exists()
    assert not (planning / "openspec" / "changes" / "app-code-standards").exists()
    assert "abk.yaml" in git(planning, "status", "--porcelain"), "left for the user to commit"


def test_a_second_run_keeps_the_edited_config(tmp_path: Path, app: Path) -> None:
    planning = tmp_path / "planning"
    main(["init", str(planning), "--repo", str(app), "--yes", "--skip-research", "--skip-propose"])
    (planning / "abk.yaml").write_text("version: 1\nrepos: {}\n")

    code = main(
        ["init", str(planning), "--repo", str(app), "--yes", "--skip-research", "--skip-propose"]
    )

    assert code == 0
    assert (planning / "abk.yaml").read_text() == "version: 1\nrepos: {}\n"


def test_repos_are_prompted_for_without_yes(tmp_path: Path, app: Path, monkeypatch) -> None:
    answers = iter([str(app), ""])
    monkeypatch.setattr(init_cmd, "ask", lambda prompt: next(answers))
    planning = tmp_path / "planning"

    code = main(["init", str(planning), "--skip-research", "--skip-propose"])

    assert code == 0
    assert "app" in load(planning / "abk.yaml").repos


def test_a_failed_proposal_is_reported_and_left(
    tmp_path: Path, app: Path, monkeypatch, capsys
) -> None:
    def bad_claude(argv, *, cwd=None):
        return "## Sources\n"  # research fine; propose writes nothing

    monkeypatch.setattr(init_cmd, "run_claude", bad_claude)
    planning = tmp_path / "planning"

    code = main(["init", str(planning), "--repo", str(app), "--yes"])

    assert code == 1
    err = capsys.readouterr().err
    assert "app-testing-infrastructure did not validate" in err


def test_bad_consumes_syntax_is_a_usage_error(tmp_path: Path, app: Path, capsys) -> None:
    code = main(["init", str(tmp_path / "p"), "--repo", str(app), "--consumes", "app", "--yes"])

    assert code == 2
    assert "--consumes takes" in capsys.readouterr().err


def test_register_store_runs_the_openspec_command(
    tmp_path: Path, app: Path, monkeypatch, capsys
) -> None:
    seen: list[list[str]] = []

    def recording(argv, *, cwd, **kwargs):
        seen.append(argv[len(openspec.command()) :])
        return fake_openspec(argv, cwd=cwd, **kwargs)

    monkeypatch.setattr(init_cmd, "run_openspec", recording)
    planning = tmp_path / "planning"

    main(
        [
            "init",
            str(planning),
            "--repo",
            str(app),
            "--yes",
            "--skip-research",
            "--skip-propose",
            "--register-store",
            "ws",
        ]
    )

    assert ["store", "register", "--id", "ws", "--yes", str(planning)] in seen
    assert "registered OpenSpec store ws" in capsys.readouterr().out


# --- install-skills ---------------------------------------------------------------------


def test_install_skills_into_a_repo_stamps_the_version(tmp_path: Path, app: Path) -> None:
    code = main(["install-skills", "--repo", str(app)])

    assert code == 0
    skill = app / ".claude" / "skills" / "abk-authoring" / "SKILL.md"
    assert f"generatedBy: agent-build-kit {__version__}" in skill.read_text()


def test_install_skills_refuses_a_hand_written_skill(tmp_path: Path, app: Path, capsys) -> None:
    mine = app / ".claude" / "skills" / "abk-config" / "SKILL.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("---\nname: abk-config\n---\nmine\n")

    code = main(["install-skills", "--repo", str(app)])

    assert code == 1
    assert mine.read_text().endswith("mine\n")
    assert "refused" in capsys.readouterr().out
    assert (app / ".claude" / "skills" / "abk-pipeline" / "SKILL.md").exists()


def test_install_skills_user_goes_to_the_home_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.chdir(tmp_path)

    code = main(["install-skills", "--user"])

    assert code == 0
    assert (tmp_path / ".claude" / "skills" / "abk-pipeline" / "SKILL.md").exists()


def test_install_skills_without_arguments_needs_a_workspace(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ABK_CONFIG", raising=False)

    code = main(["install-skills"])

    assert code == 2
    assert "--repo PATH or --user" in capsys.readouterr().err
