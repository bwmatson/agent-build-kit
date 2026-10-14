"""The python-uv profile's commands carry the tier 2 selection and can list what it selects
(spec: tier2-runtime-variants)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.pipeline.tier2 import selection_unavailable, tier2_selection
from agent_build_kit.profiles import node_npm
from agent_build_kit.profiles.python_uv import PROFILE

EXPECTED = "local_stack and not runtime_acp"


def expression() -> str:
    return tier2_selection("local_stack", ["acp"]).expression


def flat_repo(root: Path) -> Path:
    (root / "pyproject.toml").write_text('[project]\nname = "app"\n')
    (root / "tests" / "integration").mkdir(parents=True)
    (root / "tests" / "integration" / "test_live.py").write_text("")
    return root


def workspace(root: Path) -> Path:
    (root / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    for member in ("svc-a", "svc-b"):
        (root / member / "tests" / "integration").mkdir(parents=True)
        (root / member / "pyproject.toml").write_text(f'[project]\nname = "{member}"\n')
        (root / member / "tests" / "integration" / "test_live.py").write_text("")
    return root


def after_m(command: list[str]) -> str:
    return command[command.index("-m") + 1]


def test_tier2_commands_carry_the_expression_for_the_root(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker=expression())

    assert after_m(command) == EXPECTED


def test_tier2_commands_carry_the_expression_for_each_member(tmp_path: Path) -> None:
    commands = PROFILE.tier2_commands(workspace(tmp_path), marker=expression())

    assert len(commands) == 2
    assert [after_m(command) for command in commands] == [EXPECTED, EXPECTED]


def test_acceptance_commands_carry_the_expression_and_the_dev_stack_exclusion(
    tmp_path: Path,
) -> None:
    repo = workspace(tmp_path)
    paths = ["svc-a/tests/integration/test_live.py", "svc-b/tests/integration/test_live.py"]

    commands = PROFILE.acceptance_commands(
        repo, paths, marker=expression(), exclude_marker="dev_stack", root_extras=[]
    )

    assert [after_m(command) for command in commands] == [f"{EXPECTED} and not dev_stack"] * 2


def test_acceptance_commands_for_the_root_carry_the_expression(tmp_path: Path) -> None:
    repo = flat_repo(tmp_path)

    (command,) = PROFILE.acceptance_commands(
        repo,
        ["tests/integration/test_live.py"],
        marker=expression(),
        exclude_marker="",
        root_extras=[],
    )

    assert after_m(command) == EXPECTED


def test_the_repeat_command_keeps_the_expression_under_the_ids(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker=expression())

    again = PROFILE.repeat_command(command, ["tests/integration/test_live.py::test_a"])

    assert again is not None
    assert after_m(again) == EXPECTED
    assert again[-1] == "tests/integration/test_live.py::test_a"


def test_the_base_rerun_keeps_the_expression_and_drops_workers_and_paths() -> None:
    command = ["uv", "run", "pytest", "-n", "auto", "-m", EXPECTED, "tests/integration", "-q"]

    rerun = PROFILE.serial_rerun_command(command, ["tests/integration/test_live.py::test_a"])

    assert rerun == [
        "uv",
        "run",
        "pytest",
        "-m",
        EXPECTED,
        "tests/integration/test_live.py::test_a",
        "-q",
    ]
    plain = ["uv", "run", "pytest", "-n", "auto", "tests", "-q"]
    assert PROFILE.serial_rerun_command(plain, ["tests/test_a.py::test_a"]) == [
        "uv",
        "run",
        "pytest",
        "tests/test_a.py::test_a",
        "-q",
    ]


class Runner:
    """Stands in for the process run: records the command, prints a collection listing."""

    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, "")


LISTING = (
    "tests/integration/test_live.py::test_a\n"
    "tests/integration/test_live.py::TestGroup::test_b[acp]\n"
    "\n2 tests collected in 0.01s\n"
)


def test_the_listing_hook_returns_what_the_expression_selects(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner(LISTING)

    found = PROFILE.selected_tests(command, "runtime_acp", run=run)

    assert found == [
        "tests/integration/test_live.py::test_a",
        "tests/integration/test_live.py::TestGroup::test_b[acp]",
    ]
    (listed,) = run.commands
    assert after_m(listed) == "runtime_acp"
    assert "--collect-only" in listed


def test_the_listing_hook_gives_ids_from_the_repository_root_for_a_member(
    tmp_path: Path,
) -> None:
    command = PROFILE.tier2_commands(workspace(tmp_path), marker="local_stack")[0]
    run = Runner("tests/integration/test_live.py::test_a\n\n1 test collected in 0.01s\n")

    found = PROFILE.selected_tests(command, "runtime_acp", run=run)

    assert found == ["svc-a/tests/integration/test_live.py::test_a"]


def test_the_listing_hook_narrows_to_the_given_ids(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner("tests/integration/test_live.py::test_a\n\n1 test collected in 0.01s\n")

    found = PROFILE.selected_tests(
        command, "runtime_acp", run=run, among=["tests/integration/test_live.py::test_a"]
    )

    assert found == ["tests/integration/test_live.py::test_a"]
    assert "tests/integration/test_live.py::test_a" in run.commands[0]


def test_the_listing_hook_returns_nothing_selected_for_the_empty_listing(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner("\nno tests collected in 0.01s\n", returncode=5)

    assert PROFILE.selected_tests(command, "runtime_acp", run=run) == []


def test_the_listing_hook_returns_unknown_when_the_listing_fails(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner("ERROR: file or directory not found\n", returncode=4)

    assert PROFILE.selected_tests(command, "runtime_acp", run=run) is None


def test_the_python_profile_can_express_a_selection() -> None:
    assert selection_unavailable(PROFILE, dev_stack_script=False) is None


def test_a_profile_without_the_hook_cannot_express_a_selection() -> None:
    class Bare:
        name = "bare"

    reason = selection_unavailable(Bare(), dev_stack_script=False)

    assert reason is not None
    assert "bare" in reason


def test_the_node_profile_cannot_express_a_selection() -> None:
    assert selection_unavailable(node_npm.PROFILE, dev_stack_script=False) is not None


def test_a_repo_that_runs_tier_2_through_its_dev_stack_script_cannot_express_one() -> None:
    reason = selection_unavailable(PROFILE, dev_stack_script=True)

    assert reason is not None
    assert "dev stack" in reason
