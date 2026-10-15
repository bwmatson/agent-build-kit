"""`abk config` shows the merged document and what the overlay set; no writer touches the
overlay."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS
from agent_build_kit.runtimes.recommended_policy import patterns
from tests.cli.policy_apply_fakes import AGENT, CURRENT_TOOLSET, OWN, Home, installation, run_apply
from tests.cli.project_init_support import project_init

OVERLAY = {
    "verify": {"env": {"STACK_URL": {"from": "literal", "value": "http://localhost:9"}}},
    "repos": {"app": {"description": "kept locally"}},
}


def committed(root: Path, app: Path) -> Path:
    path = root / "abk.yaml"
    path.write_text(yaml.safe_dump({"repos": {"app": {"path": str(app), "slug": "example/app"}}}))
    return path


def test_config_prints_the_merged_document_and_names_what_the_overlay_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = committed(tmp_path, tmp_path / "app")
    (tmp_path / "abk.local.yaml").write_text(yaml.safe_dump(OVERLAY))

    code = main(["--config", str(path), "config"])

    captured = capsys.readouterr()
    assert code == 0
    shown = yaml.safe_load(captured.out)
    assert "STACK_URL" in shown["verify"]["env"]
    assert shown["repos"]["app"]["description"] == "kept locally"
    assert "verify" in captured.err and "repos" in captured.err
    assert "abk.local.yaml" in captured.err


def test_path_prints_both_files_when_the_overlay_exists_and_one_when_it_does_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = committed(tmp_path, tmp_path / "app")

    main(["--config", str(path), "config", "--path"])
    assert capsys.readouterr().out.split() == [str(path.resolve())]

    (tmp_path / "abk.local.yaml").write_text(yaml.safe_dump(OVERLAY))
    main(["--config", str(path), "config", "--path"])

    assert capsys.readouterr().out.split() == [
        str(path.resolve()),
        str((tmp_path / "abk.local.yaml").resolve()),
    ]


def test_project_init_reads_the_overlay_and_leaves_its_bytes_alone(tmp_path: Path) -> None:
    local_app = tmp_path / "local-app"
    local_app.mkdir()
    path = committed(tmp_path, tmp_path / "committed-app")
    overlay = tmp_path / "abk.local.yaml"
    overlay.write_text(yaml.safe_dump({"repos": {"app": {"path": str(local_app)}}}))
    before = overlay.read_bytes()

    code = project_init(path, "svc-a", "--profile", "python-uv", "--repo", "app", "--scaffold")

    assert code == 0
    assert (local_app / "svc-a" / "pyproject.toml").exists()
    assert overlay.read_bytes() == before
    registered = yaml.safe_load(path.read_text())["repos"]["app"]["projects"]
    assert [project["path"] for project in registered] == ["svc-a"]


def test_policy_apply_reads_the_overlay_and_edits_neither_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = Home(tmp_path, monkeypatch)
    home.holds(OWN, CURRENT_TOOLSET)
    path, _ = installation(tmp_path, monkeypatch, command=None)
    overlay = tmp_path / "planning" / "abk.local.yaml"
    overlay.write_text(
        yaml.safe_dump({"runtimes": {"fake": {"command": list(AGENT.variants[0].argv)}}})
    )
    assert AGENT in KNOWN_AGENTS
    committed_before, overlay_before = path.read_bytes(), overlay.read_bytes()

    code, _ = run_apply(capsys, monkeypatch, path, home, answers=("y",))

    assert code == 0
    assert patterns()[0] in home.deny()
    assert (path.read_bytes(), overlay.read_bytes()) == (committed_before, overlay_before)
