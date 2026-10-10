"""`abk init` drafts the environment section through the toolchain profiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_build_kit import profiles
from agent_build_kit.config import EnvironmentConfig
from agent_build_kit.init.environment import detect_environment
from agent_build_kit.init.scaffold import draft_config
from agent_build_kit.profiles import python_uv
from tests.init.test_scaffold import detection

EXPECTED = Path(__file__).parent.parent / "fixtures" / "init" / "python_environment.yaml"

# What a frozen sync is: it fails for exactly the unit that changed a dependency.
FROZEN = {"ci", "--frozen-lockfile", "--immutable"}


def python_repo(parent: Path) -> Path:
    """A manifest, its lock file, a path-source checkout inside it and one beside it."""
    root = parent / "app"
    (root / "vendor" / "lib").mkdir(parents=True)
    (parent / "outside").mkdir()
    for directory in (root / "vendor" / "lib", parent / "outside"):
        (directory / "pyproject.toml").write_text("[project]\nname = 'lib'\n")
        (directory / "uv.lock").write_text("")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'app'\n\n[tool.uv.sources]\n"
        "lib = { path = 'vendor/lib' }\nother = { path = '../outside' }\n"
    )
    (root / "uv.lock").write_text("")
    return root


def node_repo(root: Path, *, lock: str | None, manifest: dict | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"name": "web", **(manifest or {})}))
    if lock:
        (root / lock).write_text("")
    return root


class FakeProfile:
    """A third ecosystem's profile, registered without a change to init."""

    name = "fake-make"
    detect_markers = ("Makefile",)

    def detect_environment(self, root: Path, *, framework: bool) -> EnvironmentConfig | None:
        if not (root / "Makefile").is_file():
            return None
        return EnvironmentConfig(sync=["make", "deps"], check=["make", "check"])


class HooklessProfile:
    """A profile written before the hook existed."""

    name = "hookless"
    detect_markers = ("hookless.cfg",)


@pytest.fixture
def register(monkeypatch: pytest.MonkeyPatch):
    """The built-in profiles plus whatever a test registers, undone afterwards."""
    monkeypatch.setattr(profiles, "_REGISTRY", {})
    profiles.names()
    return profiles.register


def expected_python(key: str) -> EnvironmentConfig:
    return EnvironmentConfig.model_validate(yaml.safe_load(EXPECTED.read_text())[key])


# --- 3.1 the Python result is unchanged ----------------------------------------------


@pytest.mark.parametrize("key, framework", [("plain", False), ("framework", True)])
def test_a_python_repository_is_drafted_as_it_was_before(
    tmp_path: Path, key: str, framework: bool
) -> None:
    drafted = detect_environment(python_repo(tmp_path), framework=framework)

    assert drafted == expected_python(key)


def test_the_python_profile_drafts_the_same_section(tmp_path: Path) -> None:
    drafted = python_uv.PROFILE.detect_environment(python_repo(tmp_path), framework=False)

    assert drafted == expected_python("plain")


# --- 3.2 the node profile ------------------------------------------------------------


@pytest.mark.parametrize(
    "manager, lock",
    [("npm", "package-lock.json"), ("pnpm", "pnpm-lock.yaml"), ("yarn", "yarn.lock")],
)
def test_a_node_repository_gets_the_lock_files_managers_commands(
    tmp_path: Path, manager: str, lock: str
) -> None:
    environment = detect_environment(node_repo(tmp_path / "web", lock=lock), framework=False)

    assert environment is not None
    assert environment.sync[0] == manager and "install" in environment.sync
    assert not FROZEN & set(environment.sync)
    assert environment.check[0] == manager
    assert environment.inputs.dependencies == ["package.json"]
    assert environment.inputs.lock == [lock]
    assert environment.artifacts == ["node_modules"]


def test_a_declared_manager_wins_over_the_lock_file(tmp_path: Path) -> None:
    root = node_repo(
        tmp_path / "web", lock="package-lock.json", manifest={"packageManager": "pnpm@9.1.0"}
    )

    environment = detect_environment(root, framework=False)

    assert environment is not None
    assert environment.sync[0] == "pnpm" and environment.check[0] == "pnpm"
    assert environment.inputs.lock == ["package-lock.json"]


def test_a_node_repository_without_a_lock_file_or_declared_manager_uses_npm(
    tmp_path: Path,
) -> None:
    environment = detect_environment(node_repo(tmp_path / "web", lock=None), framework=False)

    assert environment is not None
    assert environment.sync[0] == "npm"


@pytest.mark.parametrize(
    "workspaces", [["packages/*"], {"packages": ["packages/*"]}], ids=["list", "object"]
)
def test_a_workspaces_field_becomes_manifest_patterns(tmp_path: Path, workspaces) -> None:
    root = node_repo(tmp_path / "web", lock="yarn.lock", manifest={"workspaces": workspaces})

    environment = detect_environment(root, framework=False)

    assert environment is not None
    assert environment.inputs.dependencies == ["package.json", "packages/*/package.json"]
    assert environment.inputs.lock == ["yarn.lock"]


# --- 3.3 the walk --------------------------------------------------------------------


def test_a_mixed_repository_asks_the_profile_detection_chose_first(tmp_path: Path) -> None:
    root = node_repo(python_repo(tmp_path), lock="package-lock.json")

    chose_node = detect_environment(root, framework=False, profile="node-npm")
    chose_python = detect_environment(root, framework=False, profile="python-uv")

    assert chose_node is not None and chose_node.sync[0] == "npm"
    assert chose_python is not None and chose_python.sync == ["uv", "sync"]


def test_a_python_tool_with_a_web_front_end_gives_the_python_result(tmp_path: Path) -> None:
    root = python_repo(tmp_path)
    node_repo(root / "web", lock="package-lock.json")

    environment = detect_environment(root, framework=False, profile="python-uv")

    assert environment is not None and environment.sync == ["uv", "sync"]


def test_a_chosen_profile_that_cannot_say_leaves_the_rest_to_answer(tmp_path: Path) -> None:
    root = node_repo(tmp_path / "web", lock="package-lock.json")

    environment = detect_environment(root, framework=False, profile="python-uv")

    assert environment is not None and environment.sync[0] == "npm"


def test_a_profile_without_the_hook_counts_as_returning_none(tmp_path: Path, register) -> None:
    register(HooklessProfile())

    environment = detect_environment(python_repo(tmp_path), framework=False, profile="hookless")

    assert environment is not None and environment.sync == ["uv", "sync"]


def test_nothing_recognised_is_none(tmp_path: Path, register) -> None:
    register(HooklessProfile())
    (tmp_path / "README.md").write_text("hello\n")

    assert detect_environment(tmp_path, framework=False) is None
    assert detect_environment(tmp_path, framework=False, profile="hookless") is None


def test_a_profile_registered_in_the_test_is_asked_without_a_change_to_init(
    tmp_path: Path, register
) -> None:
    register(FakeProfile())
    (tmp_path / "Makefile").write_text("deps:\n")

    environment = detect_environment(tmp_path, framework=False)

    assert environment is not None
    assert environment.sync == ["make", "deps"]


def test_a_draft_over_an_unrecognised_repository_writes_empty_commands(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "planning").mkdir()

    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=tmp_path / "planning")

    assert config.environment is not None
    assert config.environment.sync == [] and config.environment.check == []
    assert config.repos["app"].environment is None
