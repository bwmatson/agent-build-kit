"""The Python recommendations seed: the lock owns the tool versions."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

import agent_build_kit

ROOT = Path(__file__).parent.parent
SEED = Path(agent_build_kit.__file__).parent / "recommendations" / "python.md"


def section(title: str) -> str:
    parts = re.split(r"^## ", SEED.read_text(), flags=re.MULTILINE)
    return next(p for p in parts if p.startswith(title))


def test_the_seed_describes_locked_tools_and_local_hooks() -> None:
    text = SEED.read_text()

    assert "repo: local" in text
    assert "language: system" in text
    assert "uv run --frozen" in text
    assert "lock" in section("Pre-commit")


def test_the_seed_names_no_hook_rev_for_ruff_or_pyrefly() -> None:
    text = SEED.read_text()

    assert "ruff-pre-commit" not in text
    assert "pyrefly-pre-commit" not in text
    assert "--python-interpreter-path" not in text


def test_verify_steps_for_the_python_tools_are_pre_commit_runs() -> None:
    for title in ("Formatting", "Linting", "Types"):
        verifies = re.findall(r"Verify:\*\*(.*?)(?=\n\n|\n- |\Z)", section(title), flags=re.DOTALL)
        assert verifies, title
        assert all("pre-commit run" in v for v in verifies), (title, verifies)


def test_verify_hook_ids_exist_in_this_repos_pre_commit_config() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    ids = {h["id"] for r in config["repos"] for h in r["hooks"]}

    for title in ("Formatting", "Linting", "Types"):
        found = re.findall(r"pre-commit run ([\w-]+)", section(title))
        assert found, title
        assert set(found) <= ids, (title, found)
