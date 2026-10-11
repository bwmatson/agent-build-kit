"""The pytest plugin that puts the replay proxy in front of a test's external calls.

A test that asks for the `replay` fixture gets the running proxy: `addresses` for each
configured upstream and `environment()` for the code under test. The mode is the
`ABK_REPLAY_MODE` setting; the `ReplayConfig` comes from the test, by overriding the
`replay_config` fixture. The `tests.replay` section of `abk.yaml` is accepted by the schema
but not read here yet, so the default fixture has no upstream.

The calls a test makes are promoted to cassettes only once its setup, call and teardown
have all passed, which is known only after its teardown report is made, so the proxy is
finished and closed from `pytest_runtest_makereport`, not from the fixture. A test that
replayed anything is labelled `replayed` in its `user_properties`; the terminal summary lists
what replayed and what went live, and warns of recordings left waiting for review too long.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator, Mapping, Sequence
from pathlib import Path

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.config import ReplayConfig, WorkspaceConfig
from agent_build_kit.installation import Installation
from agent_build_kit.replay.hosts import InStackHosts, in_stack_hosts
from agent_build_kit.replay.models import ReplayMode, Rule
from agent_build_kit.replay.report import RunReport, combine, render, replay_label
from agent_build_kit.replay.review import count_run, overdue
from agent_build_kit.replay.state import write_report
from agent_build_kit.settings import Settings
from tests.replay.proxy import ReplayProxy, SecretInRecording

_PROXY = pytest.StashKey[ReplayProxy]()
_PASSED = pytest.StashKey[dict[str, bool]]()
# The report of each test's proxy, with the configuration it ran under.
_REPORTS = pytest.StashKey[list[tuple[ReplayConfig, RunReport]]]()
_OVERDUE = pytest.StashKey[list[str]]()


@pytest.fixture
def replay_config() -> ReplayConfig:
    """The upstreams and limits for this test; a test or a conftest overrides it."""
    return ReplayConfig()


@pytest.fixture
def replay_rules() -> Sequence[Rule]:
    """The normalisation this test declares, none by default."""
    return ()


@pytest.fixture
def replay_workspace() -> WorkspaceConfig:
    return config_module.active()


@pytest.fixture
def replay_verify_env(replay_workspace: WorkspaceConfig) -> Mapping[str, str]:
    """`verify.env` with each value resolved, as the live-stack tests get it."""
    root = config_module.active_root()
    if root is None or not replay_workspace.verify.env:
        return {}
    return Installation(replay_workspace, root).verify_env()


@pytest.fixture
def replay_in_stack(
    replay_workspace: WorkspaceConfig, replay_verify_env: Mapping[str, str]
) -> InStackHosts | None:
    """The hosts no upstream may be; None switches the check off."""
    return in_stack_hosts(replay_workspace, replay_verify_env, Settings())


@pytest.fixture
def replay_secrets() -> list[str]:
    """The values that must not appear in a recording: the settings' tokens."""
    machine = Settings()
    tokens = (machine.gh_token, machine.ado_pat, machine.gateway_master_key, machine.grafana_token)
    return [token for token in tokens if token]


@pytest.fixture
def replay(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    replay_config: ReplayConfig,
    replay_rules: Sequence[Rule],
    replay_in_stack: InStackHosts | None,
    replay_secrets: list[str],
) -> Iterator[ReplayProxy]:
    staging: Path = tmp_path_factory.mktemp("replay-staging")
    proxy = ReplayProxy(
        replay_config,
        Settings().replay_mode,
        staging=staging,
        in_stack=replay_in_stack,
        secrets=replay_secrets,
    )
    proxy.__enter__()
    request.node.stash[_PROXY] = proxy
    proxy.begin(request.node.nodeid, replay_rules)
    yield proxy
    # Finished and closed by the teardown report, which knows whether the test passed.


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    outcomes = item.stash.setdefault(_PASSED, {})
    outcomes[report.when] = report.passed
    if report.when == "teardown" and (proxy := item.stash.get(_PROXY, None)) is not None:
        try:
            proxy.finish(passed=all(outcomes.get(phase) for phase in ("setup", "call", "teardown")))
        except SecretInRecording as error:
            # The test's own result stands; the recording is what failed, and says so.
            report.outcome = "failed"
            report.longrepr = str(error)
        else:
            _note(item, report, proxy)
        finally:
            proxy.__exit__(None, None, None)
    return report


def _note(item: pytest.Item, report: pytest.TestReport, proxy: ReplayProxy) -> None:
    """Keep the proxy's report for the summary, and label the test when it replayed."""
    if proxy.mode is ReplayMode.off:
        return
    finished = proxy.report()
    item.config.stash.setdefault(_REPORTS, []).append((proxy.config, finished))
    if finished.tests and (label := replay_label(finished.tests[-1])):
        item.user_properties.append(("replay", label))
        report.user_properties = list(item.user_properties)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Count this run against each cassette waiting for review, and note the overdue ones."""
    if hasattr(session.config, "workerinput"):
        return  # one worker sees part of the run; counting and the report would be partial
    late: list[str] = []
    configs = {
        str(config.directory): config for config, _ in session.config.stash.get(_REPORTS, [])
    }
    for config in configs.values():
        write_report(
            config.directory,
            combine(
                r for c, r in session.config.stash[_REPORTS] if c.directory == config.directory
            ),
        )
        count_run(config.directory)
        late += overdue(config.directory, config.review_after_runs)
    session.config.stash[_OVERDUE] = late


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    reports = config.stash.get(_REPORTS, [])
    lines = render(combine(report for _, report in reports))
    if lines:
        terminalreporter.section("replay")
        for line in lines:
            terminalreporter.write_line(line)
    if late := config.stash.get(_OVERDUE, []):
        terminalreporter.write_line(
            f"WARNING: {len(late)} recorded call(s) have waited for review through more runs "
            "than review_after_runs allows; run `abk replay review`",
            yellow=True,
        )
