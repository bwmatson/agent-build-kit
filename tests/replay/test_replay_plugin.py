"""The plugin, run as an inner pytest session against a fake upstream."""

from pathlib import Path

import pytest

from agent_build_kit.replay.store import read_cassettes
from tests.replay.fake_upstream import FakeUpstream
from tests.replay.support import ENV, UPSTREAM

INNER = """
import httpx
import pytest

from pathlib import Path
from agent_build_kit.config import ReplayConfig, ReplayUpstream
from agent_build_kit.replay.hosts import InStackHosts


@pytest.fixture
def replay_config():
    upstream = ReplayUpstream(name="{name}", url="{url}", kind="deterministic", env=["{env}"])
    return ReplayConfig(upstreams=[upstream], directory=Path("{directory}"))


{in_stack}


@pytest.fixture
def breaks_on_teardown():
    yield
    raise RuntimeError("teardown failed")


def call(replay, text):
    return httpx.post(replay.addresses["{name}"] + "/v1/call", content=text.encode())


def test_passes(replay):
    assert call(replay, "one").content == b"echo:one"


def test_fails(replay):
    call(replay, "two")
    assert False


def test_fails_in_teardown(replay, breaks_on_teardown):
    call(replay, "three")


def test_environment(replay):
    assert replay.environment() == {environment}
"""

NOT_IN_STACK = """
@pytest.fixture
def replay_in_stack():
    return None
"""


def run(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    mode: str,
    tmp_path: Path,
    *,
    select: str,
    in_stack: str = NOT_IN_STACK,
    environment: str = "None",
) -> tuple[pytest.RunResult, Path]:
    directory = tmp_path / "cassettes"
    monkeypatch.setenv("ABK_REPLAY_MODE", mode)
    pytester.makepyfile(
        test_inner=INNER.format(
            name=UPSTREAM,
            url=upstream.url,
            env=ENV,
            directory=directory,
            in_stack=in_stack,
            environment=environment,
        )
    )
    result = pytester.runpytest_inprocess(
        "-p", "tests.replay.plugin", "-p", "no:cacheprovider", "-k", select
    )
    return result, directory


def test_a_passing_test_promotes_its_calls_and_a_failing_one_leaves_none(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    tmp_path: Path,
) -> None:
    result, directory = run(
        pytester,
        monkeypatch,
        upstream,
        "record",
        tmp_path,
        select="not test_environment",
    )

    # The third test's call passed and its teardown failed: counted as both, promoted as neither.
    result.assert_outcomes(passed=2, failed=1, errors=1)
    stored = read_cassettes(directory)
    assert [(c.test_id.rsplit("::", 1)[1], c.call_index) for c in stored] == [("test_passes", 0)]


def test_mode_off_gives_an_empty_environment_and_records_nothing(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    tmp_path: Path,
) -> None:
    result, directory = run(
        pytester,
        monkeypatch,
        upstream,
        "off",
        tmp_path,
        select="test_environment",
        environment="{}",
    )

    result.assert_outcomes(passed=1)
    assert read_cassettes(directory) == []
    assert upstream.seen == []


def test_an_upstream_inside_the_stack_is_refused_by_default(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    tmp_path: Path,
) -> None:
    result, directory = run(
        pytester,
        monkeypatch,
        upstream,
        "record",
        tmp_path,
        select="test_passes",
        in_stack="",  # the plugin's own `replay_in_stack` builds the set
    )

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*InStackUpstream*svc-a*"])
    assert read_cassettes(directory) == []
