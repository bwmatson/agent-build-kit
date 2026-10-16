"""The python-uv profile translates a tier 2 selection, carries it in its commands and can list
what it selects (spec: tier2-splits)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import Tier2Split
from agent_build_kit.pipeline.e2e import build_selection, selection_unavailable
from agent_build_kit.profiles import node_npm
from agent_build_kit.profiles.python_uv import PROFILE

EXPECTED = "local_stack and not runtime_acp"
SPLITS = (
    Tier2Split(name="acp", marker="runtime_acp"),
    Tier2Split(name="claude_code", marker="runtime_claude_code"),
    Tier2Split(name="rest"),
)


def selection(**kwargs: Any) -> Any:
    return build_selection("local_stack", SPLITS, **kwargs)


def expression(**kwargs: Any) -> str:
    return PROFILE.expression("local_stack", selection(**({"held": ["acp"]} | kwargs)))


def test_the_profile_reports_marker_as_its_one_selector_kind() -> None:
    assert PROFILE.selector_kinds == ("marker",)


def test_expression_renders_each_selection_as_the_same_m_text() -> None:
    assert expression(held=[]) == "local_stack"
    assert expression(held=["acp"]) == EXPECTED
    assert expression(held=[], only="claude_code") == "local_stack and runtime_claude_code"
    assert (
        expression(held=[], only="rest")
        == "local_stack and not runtime_acp and not runtime_claude_code"
    )
    assert expression(held=["rest"]) == "local_stack and (runtime_acp or runtime_claude_code)"


def test_an_empty_selection_has_no_expression_and_the_error_names_the_held_splits() -> None:
    held = selection(held=["acp", "claude_code", "rest"])

    with pytest.raises(ValueError, match="acp, claude_code, rest"):
        PROFILE.expression("local_stack", held)


def test_an_empty_selection_cannot_be_listed() -> None:
    held = selection(held=["acp", "claude_code", "rest"])
    run = Runner("")

    with pytest.raises(ValueError, match="acp"):
        PROFILE.list_tests(["uv", "run", "pytest"], held, run=run)

    assert run.commands == []


def test_a_plain_command_with_no_marker_reruns_without_workers_or_paths() -> None:
    command = ["uv", "run", "pytest", "-n", "auto", "tests/"]

    assert PROFILE.serial_rerun_command(command, ["tests/test_a.py::test_a"]) == [
        "uv",
        "run",
        "pytest",
        "tests/test_a.py::test_a",
        "-q",
    ]


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


def test_tier2_commands_carry_the_rendered_expression_for_the_root(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker=expression())

    assert after_m(command) == EXPECTED


def test_tier2_commands_carry_the_rendered_expression_for_each_member(tmp_path: Path) -> None:
    commands = PROFILE.tier2_commands(workspace(tmp_path), marker=expression())

    assert [after_m(command) for command in commands] == [EXPECTED, EXPECTED]


def test_acceptance_commands_carry_the_rendered_expression_and_the_dev_stack_exclusion(
    tmp_path: Path,
) -> None:
    repo = workspace(tmp_path)
    paths = ["svc-a/tests/integration/test_live.py", "svc-b/tests/integration/test_live.py"]

    commands = PROFILE.acceptance_commands(
        repo, paths, marker=expression(), exclude_marker="dev_stack", root_extras=[]
    )

    assert [after_m(command) for command in commands] == [f"{EXPECTED} and not dev_stack"] * 2


def test_acceptance_commands_for_the_root_carry_the_rendered_expression(tmp_path: Path) -> None:
    repo = flat_repo(tmp_path)

    (command,) = PROFILE.acceptance_commands(
        repo,
        ["tests/integration/test_live.py"],
        marker=expression(),
        exclude_marker="",
        root_extras=[],
    )

    assert after_m(command) == EXPECTED


def test_the_repeat_command_keeps_the_rendered_expression_under_the_ids(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker=expression())

    again = PROFILE.repeat_command(command, ["tests/integration/test_live.py::test_a"])

    assert again is not None
    assert after_m(again) == EXPECTED
    assert again[-1] == "tests/integration/test_live.py::test_a"


def test_the_serial_rerun_keeps_the_rendered_expression_and_drops_workers_and_paths() -> None:
    command = ["uv", "run", "pytest", "-n", "auto", "-m", expression(), "tests/integration", "-q"]

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


def test_list_tests_returns_what_the_selection_selects(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner(LISTING)

    found = PROFILE.list_tests(command, selection(only="acp"), run=run)

    assert found == [
        "tests/integration/test_live.py::test_a",
        "tests/integration/test_live.py::TestGroup::test_b[acp]",
    ]
    (listed,) = run.commands
    assert after_m(listed) == "local_stack and runtime_acp"
    assert "--collect-only" in listed


def test_list_tests_gives_ids_from_the_repository_root_for_a_member(tmp_path: Path) -> None:
    command = PROFILE.tier2_commands(workspace(tmp_path), marker="local_stack")[0]
    run = Runner("tests/integration/test_live.py::test_a\n\n1 test collected in 0.01s\n")

    found = PROFILE.list_tests(command, selection(only="acp"), run=run)

    assert found == ["svc-a/tests/integration/test_live.py::test_a"]


def test_list_tests_narrows_to_the_given_ids(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner("tests/integration/test_live.py::test_a\n\n1 test collected in 0.01s\n")

    found = PROFILE.list_tests(
        command, selection(only="acp"), run=run, among=["tests/integration/test_live.py::test_a"]
    )

    assert found == ["tests/integration/test_live.py::test_a"]
    assert "tests/integration/test_live.py::test_a" in run.commands[0]


def test_list_tests_returns_an_empty_list_for_the_empty_listing(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner("\nno tests collected in 0.01s\n", returncode=5)

    assert PROFILE.list_tests(command, selection(only="acp"), run=run) == []


def test_list_tests_names_tests_under_a_repo_whose_addopts_are_quiet(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-q"\nmarkers = ["local_stack", "runtime_acp"]\n'
    )
    (tmp_path / "test_live.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.local_stack\n@pytest.mark.runtime_acp\ndef test_tagged(): ...\n\n"
        "@pytest.mark.local_stack\ndef test_base(): ...\n"
    )
    command = [sys.executable, "-m", "pytest", "-m", "local_stack"]

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return subprocess.run(argv, cwd=tmp_path, **kwargs)

    found = PROFILE.list_tests(command, selection(only="acp"), run=run)

    assert found == ["test_live.py::test_tagged"]


def test_list_tests_returns_unknown_when_the_listing_fails(tmp_path: Path) -> None:
    (command,) = PROFILE.tier2_commands(flat_repo(tmp_path), marker="local_stack")
    run = Runner("ERROR: file or directory not found\n", returncode=4)

    assert PROFILE.list_tests(command, selection(only="acp"), run=run) is None


WITH_ACP = (Tier2Split(name="acp", marker="runtime_acp"), Tier2Split(name="rest"))
REST_ONLY = (Tier2Split(name="rest"),)


def test_a_profile_that_reports_no_selector_kind_is_unable_naming_it_and_the_kind() -> None:
    class Bare:
        name = "bare"

    reason = selection_unavailable(Bare(), dev_stack_script=False, splits=WITH_ACP)

    assert reason is not None
    assert "bare" in reason
    assert "marker" in reason


def test_the_node_profile_is_unable_to_apply_a_marker() -> None:
    reason = selection_unavailable(node_npm.PROFILE, dev_stack_script=False, splits=WITH_ACP)

    assert reason is not None
    assert node_npm.PROFILE.name in reason
    assert "marker" in reason


def test_a_selector_kind_the_profile_lacks_names_the_kinds_it_supports() -> None:
    class Globs:
        name = "globs"
        selector_kinds = ("path",)

        def expression(self, marker: str, selection: Any) -> str:
            return marker

        def list_tests(self, command: list[str], selection: Any, **_: Any) -> list[str] | None:
            return None

    reason = selection_unavailable(Globs(), dev_stack_script=False, splits=WITH_ACP)

    assert reason is not None
    assert "globs" in reason
    assert "marker" in reason
    assert "path" in reason


def test_only_a_repo_with_a_declared_split_can_be_unable() -> None:
    # The python profile applies a marker selector; a dev stack script cannot take one.
    assert selection_unavailable(PROFILE, dev_stack_script=False, splits=WITH_ACP) is None
    reason = selection_unavailable(PROFILE, dev_stack_script=True, splits=WITH_ACP)
    assert reason is not None
    assert "dev stack" in reason

    for profile in (PROFILE, node_npm.PROFILE):
        assert selection_unavailable(profile, dev_stack_script=True, splits=REST_ONLY) is None
        assert selection_unavailable(profile, dev_stack_script=False, splits=REST_ONLY) is None
