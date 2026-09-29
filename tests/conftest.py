"""Guards and fixtures that apply to every test in the suite.

The suite once scheduled a real systemd timer on the developer's machine every
time it ran, through tests that reach `pause_until` without injecting a
scheduler. A test that needs the scheduler injects its own; everything else
gets one that fails loudly rather than touching the host. The same goes for
refreshing the Claude login, for spawning a real agent, and for the adapter's
reading of the real usage window.

Every test also runs against a workspace: the leaf modules read the branch
prefix, the repo set and the limits from `config.active()`, so a default
workspace with two repos — `app`, which consumes `platform` — is activated for
each test, on a temporary planning root. Tests that need a different shape
build their own `Installation` and activate it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import RepoConfig, WorkspaceConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import pause, usage_guard
from agent_build_kit.runtimes import claude_code


@pytest.fixture(autouse=True)
def no_real_timers(monkeypatch: pytest.MonkeyPatch) -> None:
    real = pause.systemd_resume

    def refuse(seconds, command, *, working_directory=None, run=None):
        # A test that injects `run` is testing the scheduler itself, and never
        # reaches systemd.
        if run is not None:
            return real(seconds, command, working_directory=working_directory, run=run)
        raise AssertionError("a test tried to schedule a real systemd timer — inject `schedule=`")

    monkeypatch.setattr(pause, "systemd_resume", refuse)


@pytest.fixture(autouse=True)
def no_real_login_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refreshing the login is a real `claude` call. A test that means to
    exercise it injects `refresh=`; anything else reaching it fails."""

    def refuse() -> None:
        raise AssertionError("a test tried to make a real claude call to refresh the login")

    monkeypatch.setattr(usage_guard, "refresh_login", refuse)


@pytest.fixture(autouse=True)
def no_real_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running an agent through the runtime adapter is a real `claude`
    process. A test that means to run one injects `execute=`; anything else
    reaching the adapter's real executor fails. A call site that still spawns
    `claude` itself is stopped by `no_direct_claude` instead."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to spawn a real agent process — inject `execute=`")

    monkeypatch.setattr(claude_code, "spawn", refuse)


@pytest.fixture(autouse=True)
def no_real_usage_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter's default usage readers call the live endpoint with the
    machine's own token, and read the machine's own Claude Code cache. A test
    that means to read usage injects `read_live=` and `read_cached=`."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a test tried to read this machine's real usage window — inject `read_live=`"
            " and `read_cached=`"
        )

    monkeypatch.setattr(claude_code, "read_live_usage", refuse)
    monkeypatch.setattr(claude_code, "read_cached_usage", refuse)


class _NoClaudePopen(subprocess.Popen):
    """`subprocess.Popen`, refusing to start a `claude` process. Every other
    command — git, the fixture repos' own tools — runs as it would."""

    def __init__(self, args, *pargs, **kwargs) -> None:
        program = args[0] if isinstance(args, list | tuple) and args else args
        if Path(str(program)).name == "claude":
            raise AssertionError(
                "a test spawned `claude` directly, not through the agent runtime — "
                "inject a runtime, or `execute=` on the adapter"
            )
        super().__init__(args, *pargs, **kwargs)


@pytest.fixture(autouse=True)
def no_direct_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behind `no_real_agent`: a call site that builds and spawns its own
    `claude` argv, instead of going through the runtime, fails rather than
    starting a real agent on the machine running the suite."""
    monkeypatch.setattr(subprocess, "Popen", _NoClaudePopen)


def workspace_config(root: Path, **overrides) -> WorkspaceConfig:
    """Two repos on a temporary root: `app` consumes `platform`."""
    repos = {
        "platform": RepoConfig(path=root / "checkouts" / "platform", slug="example/platform"),
        "app": RepoConfig(
            path=root / "checkouts" / "app", slug="example/app", consumes=["platform"]
        ),
    }
    return WorkspaceConfig.model_validate(
        {"repos": {k: v.model_dump(mode="json") for k, v in repos.items()}, **overrides}
    )


def make_installation(root: Path, **overrides) -> Installation:
    root.mkdir(parents=True, exist_ok=True)
    installation = Installation(workspace_config(root, **overrides), root)
    installation.activate()
    return installation


@pytest.fixture(autouse=True)
def workspace(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """The default workspace every test sees, on its own planning root."""
    root = tmp_path_factory.mktemp("planning")
    installation = make_installation(root)
    yield installation
    config_module.activate(WorkspaceConfig(), None)


@pytest.fixture
def installation(tmp_path: Path) -> Installation:
    """A workspace rooted at the test's own tmp_path (state, specs and graph
    page under it), for tests that write planning-repo files."""
    return make_installation(tmp_path)
