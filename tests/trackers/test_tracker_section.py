"""The `repos.<name>.tracker` section: off by default, validated per repo, forge-independent."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import config as config_module
from agent_build_kit import trackers
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import Review
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.trackers.config import TrackerConfigError, section_for
from tests.conftest import make_installation
from tests.graph_driver import fresh
from tests.runner_fakes import make_runner

AZURE = {
    "kind": "azure_devops",
    "organization": "example-org",
    "project": "Example Project",
    "team": "Example Team",
    "area_path": "Example Project\\Area",
    "iteration_path": "Example Project\\Iteration 1",
    "story_type": "User Story",
    "token_env": "TRACKER_PAT",
}
LABELS = {"feature": "type:feature", "story": "type:story", "task": "type:task"}
GITHUB = {
    "kind": "github",
    "owner": "example",
    "repo": "app",
    "labels": LABELS,
    "token_env": "TRACKER_TOKEN",
}
# Shaped like a real personal access token, which a section must never hold.
TOKEN_SHAPED = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def configure(**trackers_by_repo: dict[str, Any] | None) -> None:
    """Activate the default workspace with these repos' `tracker` sections set."""
    current = config_module.active()
    repos = {
        name: repo.model_copy(update={"tracker": trackers_by_repo.get(name, repo.tracker)})
        for name, repo in current.repos.items()
    }
    config_module.activate(current.model_copy(update={"repos": repos}), config_module.active_root())


def test_a_repo_with_no_section_is_off() -> None:
    configure(app=None)

    assert section_for("app") is None
    assert trackers.for_repo("app") is None
    assert trackers.enabled("app") is False


def test_kind_none_is_the_same_as_no_section() -> None:
    configure(app={"kind": "none"})

    assert section_for("app") is None
    assert trackers.for_repo("app") is None
    assert trackers.enabled("app") is False


def test_a_valid_section_is_on_and_answers_its_kind() -> None:
    configure(app=AZURE)

    section = section_for("app")

    assert section is not None and section.kind == "azure_devops"
    assert trackers.enabled("app") is True


def test_a_missing_target_field_is_named_with_its_repo_and_kind() -> None:
    configure(app={key: value for key, value in AZURE.items() if key != "project"})

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    message = str(raised.value)
    assert "project" in message
    assert "app" in message
    assert "azure_devops" in message


def test_a_github_section_without_every_kind_label_is_refused() -> None:
    labels = {kind: label for kind, label in LABELS.items() if kind != "task"}
    configure(app={**GITHUB, "labels": labels})

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    message = str(raised.value)
    assert all(word in message for word in ("app", "github", "labels", "task"))


def test_a_github_section_with_an_empty_label_is_refused() -> None:
    configure(app={**GITHUB, "labels": {**LABELS, "story": ""}})

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert "labels" in str(raised.value) and "story" in str(raised.value)


def test_a_section_with_target_fields_and_no_kind_is_an_error_not_off() -> None:
    configure(app={key: value for key, value in AZURE.items() if key != "kind"})

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert "app" in str(raised.value) and "kind" in str(raised.value)
    with pytest.raises(TrackerConfigError):
        trackers.enabled("app")


def test_a_token_shaped_credential_is_refused_without_printing_it() -> None:
    configure(app={**GITHUB, "token_env": TOKEN_SHAPED})

    with pytest.raises(TrackerConfigError) as raised:
        section_for("app")

    assert "token_env" in str(raised.value)
    assert TOKEN_SHAPED not in str(raised.value)
    assert TOKEN_SHAPED not in repr(raised.value)


def test_a_bad_section_stops_only_its_own_repo() -> None:
    configure(app={"kind": "github", "owner": "example"}, platform=None)

    with pytest.raises(TrackerConfigError) as raised:
        trackers.enabled("app")

    assert "app" in str(raised.value)
    assert trackers.enabled("platform") is False
    assert trackers.for_repo("platform") is None


def test_the_tracker_comes_from_its_own_section_whatever_the_forge_is() -> None:
    forge_settings = {"org": "forge-org", "project": "Forge Project", "repo": "forge-repo"}
    config = config_module.active()
    repos = {
        **config.repos,
        "app": RepoConfig.model_validate(
            {
                **config.repos["app"].model_dump(mode="json"),
                "forge": "azure_devops",
                "azure_devops": forge_settings,
                "tracker": GITHUB,
            }
        ),
    }
    config_module.activate(config.model_copy(update={"repos": repos}), config_module.active_root())

    section = section_for("app")

    assert section is not None and section.kind == "github"
    dumped = section.model_dump_json()
    assert "example" in dumped
    for forge_value in forge_settings.values():
        assert forge_value not in dumped


@pytest.fixture
def quiet_tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    """A tick over the fixture units with every outside call faked."""
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_concurrent_stacks": 1},
    )
    recorder = fresh(tmp_path)
    monkeypatch.setattr(
        cli, "build_runner", lambda u, **kw: make_runner(recorder.store, recorder, tmp_path)
    )
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))
    monkeypatch.setattr(
        cli, "build_fetch_review", lambda **_: lambda repo, pr: Review(lines=["rename the marker"])
    )
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    return inst


def test_a_tick_with_no_section_makes_no_tracker_call_and_writes_no_file(
    quiet_tick: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    real = trackers.for_repo

    def recording(name: str) -> object:
        asked.append(name)
        return real(name)

    monkeypatch.setattr(trackers, "for_repo", recording)
    names = list(config_module.active().repos)

    ran = cli.cmd_tick(argparse.Namespace(dry_run=False, only=None), quiet_tick)

    assert ran == 0
    assert [trackers.enabled(name) for name in names] == [False] * len(names)
    # Nothing in a tick asks for a tracker yet; a later change that wires one in must ask
    # only about a repo whose section is on, so this changes with it.
    assert asked == []
    assert [p for p in tmp_path.rglob("*") if "tracker" in p.name.lower()] == []
