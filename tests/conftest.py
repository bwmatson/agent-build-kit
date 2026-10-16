"""Guards and fixtures that apply to every test in the suite.

Nothing a test runs may touch the host: refreshing the Claude login, spawning a
real agent, the adapter's reading of the real usage window and any `gh` call
each fail loudly here unless a test injects its own. A test marked
`local_stack` is the exception for the agent: the runtime's spawn and a
program named `claude` are let through. The guards on the login refresh, the
usage window, `gh` and the code host apply to it too.

Every test also runs against a workspace: the leaf modules read the branch
prefix, the repo set and the limits from `config.active()`, so a default
workspace with two repos — `app`, which consumes `platform` — is activated for
each test, on a temporary planning root. Tests that need a different shape
build their own `Installation` and activate it.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import claude_account, forges
from agent_build_kit import config as config_module
from agent_build_kit.cli import doctor
from agent_build_kit.cli import pipeline as pipeline_cli
from agent_build_kit.config import RepoConfig, WorkspaceConfig
from agent_build_kit.forges import github
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.runtimes import claude_code
from tests.forges.github_server import FakeGitHub
from tests.forges.mock_host import MockHost, ok, recorded
from tests.usage_host import Host

pytest_plugins = [
    "pytester",
    "tests.account_settings",
    "tests.fork_warning_guard",
    "tests.replay.plugin",
    "tests.runtime_tags",
    "tests.time_limit",
    "tests.time_split",
]


@pytest.fixture(autouse=True)
def no_real_loginctl(monkeypatch: pytest.MonkeyPatch) -> None:
    """`loginctl` is the developer's machine, not the suite's.

    Asking it whether lingering is on makes a test's output depend on whose
    machine runs it (and wait on a slow or missing logind), and asking it to
    enable lingering changes the machine. So by default the timers module sees
    a host with no `loginctl`: the state is unknown and nothing is said, and a
    test that reaches the enabling call fails. A test of the check injects a
    runner or replaces `timers.subprocess`.
    """
    import subprocess

    from agent_build_kit import timers

    class NoLoginctl:
        def run(self, argv, **kwargs):
            if argv[0] == "loginctl":
                if "enable-linger" in argv:
                    pytest.fail(f"a test reached the real loginctl: {argv}")
                raise FileNotFoundError("loginctl")
            return subprocess.run(argv, **kwargs)

        def __getattr__(self, name: str):
            return getattr(subprocess, name)

    monkeypatch.setattr(timers, "subprocess", NoLoginctl())


@pytest.fixture(autouse=True)
def no_real_unit_directory(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The systemd user directory is the developer's machine, not the suite's.

    `abk doctor` looks at the units installed there, and an install writes to
    it, so a test that does either without being pointed elsewhere would pass
    or fail depending on whose machine it runs on — or rewrite the real timers.
    """
    from agent_build_kit.settings import settings

    monkeypatch.setattr(settings, "config_home", tmp_path_factory.mktemp("config-home"))
    # The pipeline's environment names the live installation; the settings read it at import,
    # so a command run without `--config` would act on that installation's state.
    monkeypatch.setattr(settings, "config", None)
    # The account a `claude` runs on is the developer's or builder's own: a test that wants one
    # sets it, and none inherits it from the process.
    monkeypatch.setattr(settings, "claude_home", None)
    for name in claude_account.NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_real_login_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refreshing the login is a real `claude` call. A test that means to
    exercise it injects `refresh=`; anything else reaching it fails. Patched
    in the adapter, which makes the call: `usage_guard.refresh_login` hands
    it there."""

    def refuse() -> None:
        raise AssertionError("a test tried to make a real claude call to refresh the login")

    monkeypatch.setattr(claude_code, "refresh_login", refuse)


@pytest.fixture(autouse=True)
def no_real_agent(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running an agent through the runtime adapter is a real `claude`
    process. A test that means to run one injects `execute=`; anything else
    reaching the adapter's real executor fails. A call site that still spawns
    `claude` itself is stopped by `no_direct_claude` instead.

    Not applied to a `local_stack` test (on the test, its class or its
    module): that marker means the test drives a real agent."""
    if request.node.get_closest_marker("local_stack"):
        return

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to spawn a real agent process — inject `execute=`")

    monkeypatch.setattr(claude_code, "spawn", refuse)


@pytest.fixture(autouse=True)
def no_real_usage_reading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The adapter's default usage readers call the live endpoint with the
    machine's own token, and read the machine's own Claude Code cache. A test
    that means to read usage injects `read_live=` and `read_cached=`. The
    guard's own default cache path points at a file that does not exist, so a
    fresh block in the machine's `~/.claude.json` cannot change a decision; a
    test that wants a cache file sets `DEFAULT_ANCHOR_PATH` itself."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a test tried to read this machine's real usage window — inject `read_live=`"
            " and `read_cached=`"
        )

    monkeypatch.setattr(claude_code, "read_live_usage", refuse)
    monkeypatch.setattr(claude_code, "read_cached_usage", refuse)
    monkeypatch.setattr(usage_guard, "DEFAULT_ANCHOR_PATH", tmp_path / "no-claude.json")


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
def no_direct_claude(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Behind `no_real_agent`: a call site that builds and spawns its own
    `claude` argv, instead of going through the runtime, fails rather than
    starting a real agent on the machine running the suite.

    Not applied to a `local_stack` test: the real runtime starts `claude`
    through `subprocess.Popen`, so lifting `no_real_agent` alone would change
    nothing. Every other test still finds a bypassing call site here."""
    if request.node.get_closest_marker("local_stack"):
        return
    monkeypatch.setattr(subprocess, "Popen", _NoClaudePopen)


@pytest.fixture(autouse=True)
def no_real_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `gh` call from a test reaches GitHub, over the network and as whoever
    is logged in. One such call — creating a label on a repo the fixtures name
    `example/platform` — answered in three seconds, long enough for a test that
    waits on a timer to give up on a different event and fail one run in three.
    A test that means to run `gh` replaces `subprocess.run` itself, as
    `test_shell.py` does; anything else reaching it fails and names the
    command."""
    real = subprocess.run

    def run(args, *rest, **kwargs):
        if isinstance(args, (list, tuple)) and args and str(args[0]) == "gh":
            raise AssertionError(
                f"a test tried to run a real gh command: {' '.join(map(str, args))}"
            )
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)


@pytest.fixture(autouse=True)
def no_real_github() -> Iterator[None]:
    """The registered GitHub forge answers from a stand-in host, so no caller
    of `forges.get("github")` reaches api.github.com."""
    forges.names()  # load the built-ins before one is replaced
    forges.register(GitHubForge(http=MockHost(ok({"message": "Not Found"}, 404))))
    yield
    forges.register(github.FORGE)


@pytest.fixture(autouse=True)
def no_real_forge_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """`abk doctor` asks GitHub who each repo's credential is. A test that
    means to choose the answer passes `transport=`; any other call gets the
    recorded account, so no doctor caller reaches api.github.com."""
    real = doctor.Transport

    def build(base_url, credentials, *, transport=None, **kwargs):
        host = transport or MockHost(recorded("user_200"))
        return real(base_url, credentials, transport=host, **kwargs)

    clear_credentials()
    monkeypatch.setattr(doctor, "Transport", build)


@pytest.fixture
def github_server() -> Iterator[FakeGitHub]:
    """A fake GitHub host on a free local port, stopped after the test."""
    with FakeGitHub() as server:
        yield server


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


def status_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    units: list[StoredUnit],
    *,
    limit: int | None = None,
) -> list[str]:
    """`abk status` over `units`. `upsert` drops a unit's state, branch and pull request, so
    those are recorded after it; `limit` is `project_limits.max_units_in_progress`."""
    limits = {} if limit is None else dict(project_limits=dict(max_units_in_progress=limit))
    workspace = make_installation(
        tmp_path,
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
        **limits,
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(units)
    for unit in units:
        if unit.state != "planned" or unit.branch:
            store.set_state(unit.id, unit.state, branch=unit.branch, pr=unit.pr)
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)
    assert pipeline_cli.cmd_status(argparse.Namespace(), workspace) == 0
    return capsys.readouterr().out.splitlines()


@pytest.fixture(autouse=True)
def workspace(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """The default workspace every test sees, on its own planning root. A
    runtime or model the developer's shell selects is not the suite's."""
    for key in (
        "ABK_CONFIG",
        "ABK_RUNTIME",
        "ABK_IMPLEMENT_MODEL",
        "ABK_REWORK_MODEL",
        "ABK_REVIEW_MODEL",
        "ABK_REWORK_REVIEW_MODEL",
        "ABK_OTEL_ENABLED",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    ):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path_factory.mktemp("planning")
    installation = make_installation(root)
    yield installation
    config_module.activate(WorkspaceConfig(), None)


@pytest.fixture
def scripted_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs a unit by calling `.run(unit, base=, graph=)` on whatever
    `build_runner` returns when it has one, in place of the unit's thread, so a
    tick test can script what a build does and check what the tick makes of
    it. A real `UnitRunner` runs its thread."""
    from agent_build_kit.cli import pipeline as cli
    from agent_build_kit.pipeline.stack_runner import UnitRunner

    on_thread = cli.run_unit_thread

    def run(inst, runner, unit, *, base, graph, run_log):
        if not isinstance(runner, UnitRunner):
            return runner.run(unit, base=base, graph=graph)
        return on_thread(inst, runner, unit, base=base, graph=graph, run_log=run_log)

    monkeypatch.setattr(cli, "run_unit_thread", run)


@pytest.fixture
def installation(tmp_path: Path) -> Installation:
    """A workspace rooted at the test's own tmp_path (state, specs and graph
    page under it), for tests that write planning-repo files."""
    return make_installation(tmp_path)


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Host:
    """The usage endpoint faked at the HTTP boundary, on a home of its own."""
    return Host(tmp_path, monkeypatch)
