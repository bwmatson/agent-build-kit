"""`abk project init --scaffold` writes the least a profile's detection recognises, and never
overwrites (spec: project-init)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from agent_build_kit.init.detect import detect_projects
from tests.cli.project_init_support import project_init, write_commented


def test_a_python_project_gets_a_minimal_pyproject_detection_recognises(tmp_path: Path) -> None:
    config = write_commented(tmp_path)
    app = tmp_path / "app"

    code = project_init(
        config, "agent-assessment", "--profile", "python-uv", "--repo", "app", "--scaffold"
    )

    assert code == 0
    project = tomllib.loads((app / "agent-assessment" / "pyproject.toml").read_text())["project"]
    assert project["name"] and project["version"] and project["requires-python"]
    found = {p.path: p for p in detect_projects(app)}
    assert found["agent-assessment"].languages == ["python"]
    assert found["agent-assessment"].profile == "python-uv"


def test_a_node_project_gets_a_minimal_package_json(tmp_path: Path) -> None:
    config = write_commented(tmp_path)
    app = tmp_path / "app"

    code = project_init(config, "web", "--profile", "node-npm", "--repo", "app", "--scaffold")

    assert code == 0
    package = json.loads((app / "web" / "package.json").read_text())
    assert package["name"] and package["version"]
    found = {p.path: p for p in detect_projects(app)}
    assert found["web"].profile == "node-npm"


def test_an_existing_manifest_is_left_alone_and_reported(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)
    manifest = tmp_path / "app" / "svc-b" / "pyproject.toml"
    manifest.parent.mkdir()
    original = '[project]\nname = "mine"\nversion = "9.9.9"\n'
    manifest.write_text(original)

    code = project_init(config, "svc-b", "--profile", "python-uv", "--repo", "app", "--scaffold")

    assert code == 0
    assert manifest.read_text() == original
    assert "left alone" in capsys.readouterr().out
