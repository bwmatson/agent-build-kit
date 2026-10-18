"""A builder may run `abk install-config`, a reviewer and a planner may not, and an install is
on the unit's run log (spec: config-install)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.pipeline import planner, stack_runner
from agent_build_kit.pipeline.wiring import allowed_tools, build_run, build_run_review
from agent_build_kit.profiles.python_uv import PROFILE
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.tool_patterns import allows
from tests.conftest import make_installation
from tests.prompt_text import filled, flat
from tests.runtimes.claude_cli import FakeClaude, replied, stream

INSTALL = "abk install-config .abk/proposed/p.yaml pkg/.pre-commit-config.yaml"
STAGED = "repos: []\n"
TOOL_CALL = "toolu_01InstallConfigCall"
BUILDER_PROMPTS = [
    "TESTS_PROMPT",
    "IMPLEMENTATION_PROMPT",
    "REVIEW_FEEDBACK_PROMPT",
    "CHECKS_PROMPT",
    "REWORK_PROMPT",
    "ADAPT_PROMPT",
]


def allowed_in(argv: list[str]) -> str:
    return argv[argv.index("--allowedTools") + 1]


def test_a_builder_may_install_a_config_file_and_a_reviewer_and_a_planner_may_not(
    tmp_path: Path,
) -> None:
    planning = tmp_path / "planning"
    make_installation(planning)
    tree = tmp_path / "tree"
    tree.mkdir()
    forge = forges.get("github")
    review_claude = FakeClaude(stdout=replied(tree, "Looks fine."))
    plan_claude = FakeClaude(stdout=replied(tree, "{}"))

    build_run_review(
        runtime=ClaudeCodeRuntime(execute=review_claude), planning_repo=planning, forge=forge
    )(cwd=tree)
    with pytest.raises(planner.PlannerError):
        planner.plan_round(
            changes={"feature": "# feature"},
            in_flight=[],
            runtime=ClaudeCodeRuntime(execute=plan_claude),
        )

    assert allows(allowed_tools(PROFILE, forge), INSTALL)
    assert not allows(allowed_in(review_claude.argv), INSTALL)
    assert "install-config" not in " ".join(plan_claude.argv)


@pytest.mark.parametrize("name", BUILDER_PROMPTS)
def test_a_builder_prompt_names_the_command_the_staging_directory_and_the_allow_list(
    name: str,
) -> None:
    text = flat(filled(getattr(stack_runner, name)))

    assert "abk install-config" in text
    assert ".abk/proposed/" in text
    assert ".pre-commit-config.yaml" in text


def test_an_install_is_written_to_the_units_run_log(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    make_installation(planning)
    tree = tmp_path / "tree"
    tree.mkdir()
    digest = hashlib.sha256(STAGED.encode()).hexdigest()
    target = "pkg/.pre-commit-config.yaml"
    events = stream(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": TOOL_CALL,
                        "name": "Bash",
                        "input": {"command": INSTALL},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": TOOL_CALL,
                        "content": f"installed {target} sha256={digest} size={len(STAGED)}",
                    }
                ],
            },
        },
    )
    lines: list[str] = []
    run = build_run(
        runtime=ClaudeCodeRuntime(execute=FakeClaude(stdout=events + replied(tree, "Done."))),
        planning_repo=planning,
        log=lines.append,
    )

    run("Implement it.", cwd=tree)

    (logged,) = [line for line in lines if digest in line]
    assert target in logged
