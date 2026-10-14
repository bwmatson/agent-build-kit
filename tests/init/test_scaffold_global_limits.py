"""`abk init` writes the generated-file patterns under `global_limits`."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.config import load
from tests.cli.test_init_environment import (
    SOURCES,
    code_repo,
    planning_with,
    run_init,
    stubs,  # noqa: F401  (the autouse fixture that fakes the agent and the prompts)
    written,
)


def installation(tmp_path: Path) -> tuple[Path, Path]:
    app = code_repo(tmp_path, "app", **{"uv.lock": ""})
    planning = planning_with(tmp_path, **{"pyproject.toml": SOURCES, "uv.lock": ""})
    return planning, app


def test_a_new_file_gets_the_patterns_under_global_limits(tmp_path: Path) -> None:
    planning, app = installation(tmp_path)

    assert run_init(planning, app) == 0

    config = written(planning)
    assert "uv.lock" in config["global_limits"]["generated_files"]
    assert "limits" not in config


def test_an_existing_global_limits_is_extended_in_place(tmp_path: Path) -> None:
    planning, app = installation(tmp_path)
    run_init(planning, app)
    config = written(planning)
    config["global_limits"] = {"max_unit_lines": 900}
    config["environment"] = {"sync": ["my-sync"], "check": ["my-check"]}
    (planning / "abk.yaml").write_text(yaml.safe_dump(config))

    assert run_init(planning, app) == 0

    after = written(planning)
    assert "uv.lock" in after["global_limits"]["generated_files"]
    assert after["global_limits"]["max_unit_lines"] == 900
    assert "limits" not in after


def test_an_existing_limits_block_is_extended_in_place_when_there_is_no_global_limits(
    tmp_path: Path,
) -> None:
    planning, app = installation(tmp_path)
    run_init(planning, app)
    config = written(planning)
    config.pop("global_limits", None)
    config["limits"] = {"max_unit_lines": 900}
    config["environment"] = {"sync": ["my-sync"], "check": ["my-check"]}
    (planning / "abk.yaml").write_text(yaml.safe_dump(config))

    assert run_init(planning, app) == 0

    after = written(planning)
    assert "uv.lock" in after["limits"]["generated_files"]
    assert after["limits"]["max_unit_lines"] == 900
    assert "global_limits" not in after
    block = load(planning / "abk.yaml").global_limits  # pyrefly: ignore
    assert "uv.lock" in block.generated_files
