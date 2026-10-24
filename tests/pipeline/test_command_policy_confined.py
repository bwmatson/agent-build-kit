"""When the step is confined, the command rules stand down the planning repo's `abk.yaml` and
`abk.local.yaml` text fence, except for the file inside the checkout; every other rule applies in
both modes (spec: sandbox-guard-fallback)."""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.command_policy import Verdict, check_command

BRANCH = "spec/change/1"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = tmp_path.resolve() / "unit"
    (path / ".abk" / "out" / "run-1").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", BRANCH], cwd=path, check=True)
    return path


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    path = tmp_path.resolve() / "planning"
    path.mkdir()
    return path


def routes(config: Path) -> dict[str, str]:
    return {
        "redirect": f"echo x > {config}",
        "tee": f"echo x | tee {config}",
        "cp": f"cp /tmp/mine.yaml {config}",
        "mv": f"mv /tmp/mine.yaml {config}",
        "dd": f"dd if=/tmp/mine.yaml of={config}",
        "sed -i": f"sed -i s/a/b/ {config}",
    }


def verdict(command: str, worktree: Path, fenced: tuple[Path, ...], confined: bool) -> Verdict:
    return check_command(
        command, branch=BRANCH, worktree=worktree, fenced=fenced, confined=confined
    )


def stands_down(worktree: Path, planning: Path) -> bool:
    """Whether a confined run may write the planning repo's configuration from a command."""
    config = planning / "abk.yaml"
    return verdict(f"echo x > {config}", worktree, (config,), True).allowed


@pytest.mark.parametrize("name", ["abk.yaml", "abk.local.yaml"])
def test_every_route_onto_the_planning_config_is_refused_unless_confined(
    name: str, worktree: Path, planning: Path
) -> None:
    config = planning / name
    for route, command in routes(config).items():
        assert not verdict(command, worktree, (config,), False).allowed, route
        assert verdict(command, worktree, (config,), True).allowed, route


def test_the_config_inside_the_checkout_stays_fenced_when_confined(
    worktree: Path, planning: Path
) -> None:
    config = worktree / "abk.yaml"

    assert stands_down(worktree, planning)
    for route, command in routes(config).items():
        assert not verdict(command, worktree, (config,), True).allowed, route


@pytest.mark.parametrize("confined", [False, True])
@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 4",
        "git push origin main",
        "git push --force origin spec/change/1",
        "git commit --no-verify -m x",
        "echo x > src/app.py",
    ],
)
def test_the_meaning_guards_and_the_redirect_rule_apply_in_both_modes(
    command: str, confined: bool, worktree: Path, planning: Path
) -> None:
    assert stands_down(worktree, planning)
    assert not verdict(command, worktree, (), confined).allowed


@pytest.mark.parametrize("confined", [False, True])
def test_a_redirect_into_the_run_folder_is_allowed_in_both_modes(
    confined: bool, worktree: Path, planning: Path
) -> None:
    command = "uv run pytest > $ABK_OUT/suite.log 2>&1"

    assert stands_down(worktree, planning)
    assert verdict(command, worktree, (), confined).allowed


def test_with_no_worktree_known_every_fenced_file_stays_fenced_when_confined(
    planning: Path,
) -> None:
    config = planning / "abk.yaml"

    result = check_command(
        f"echo x > {config}", branch=BRANCH, worktree=None, fenced=(config,), confined=True
    )

    assert not result.allowed
