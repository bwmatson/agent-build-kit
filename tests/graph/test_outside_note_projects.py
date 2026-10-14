"""The test files an outside commit's note lists are the ones the profile of each file's
project says are tests (spec: node-npm-red-and-stubs).

The branch and the agent are those of `test_outside_commits_prompt.py`; the repository
declares a Python root project and a node project beneath it.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ProjectConfig, RepoConfig
from tests.graph.test_outside_commits_prompt import ADOPTED, FREE_SESSION, branch, drive, land
from tests.graph_driver import tick


def test_a_node_test_in_a_node_project_is_listed_with_the_decision_asked(tmp_path: Path) -> None:
    repo = branch(tmp_path)
    recorder, builder, overrides = drive(tmp_path)
    overrides["repo_config"] = RepoConfig(
        path=repo,
        changelog=None,
        profile="python-uv",
        projects=[
            ProjectConfig(path=".", profile="python-uv"),
            ProjectConfig(path="web", profile="node-npm"),
        ],
    )
    tick(tmp_path, recorder, **overrides)
    land(
        repo,
        "Reword the widget test",
        {
            "web/src/widget.test.tsx": "// the test\n",
            "web/src/widget.ts": "export const w = 1\n",
            "tests/test_notes.py": "def test_note(): ...\n",
        },
        FREE_SESSION,
    )
    recorder.tier1_results = [(False, "lint: nope"), (True, "")]

    tick(tmp_path, recorder, event=ADOPTED, **overrides)
    tick(tmp_path, recorder, **overrides)

    [prompt] = builder.by_step["claude:fix_checks"]
    [changed] = [line for line in prompt.splitlines() if line.startswith("Tests changed by")]
    assert "web/src/widget.test.tsx" in changed
    assert "tests/test_notes.py" in changed
    assert "web/src/widget.ts" not in changed
