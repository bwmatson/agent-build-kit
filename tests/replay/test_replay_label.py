"""The plugin, run as an inner pytest session: the label a replayed test carries, the report in
the terminal summary, and the warning for recordings left waiting for review."""

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.shell import git
from agent_build_kit.replay.report import RunReport
from agent_build_kit.replay.state import REPORT_FILE, ReplayState, read_state, write_state
from agent_build_kit.replay.store import cassette_name, write_cassette
from tests.factories import init_repo
from tests.replay.fake_upstream import FakeUpstream
from tests.replay.support import ENV, UPSTREAM, run_session, waiting_cassette

INNER = """
import os

import httpx
import pytest

from pathlib import Path
from agent_build_kit.config import ReplayConfig, ReplayUpstream


@pytest.fixture
def replay_config():
    upstream = ReplayUpstream(name="{name}", url="{url}", kind="deterministic", env=["{env}"])
    return ReplayConfig(upstreams=[upstream], directory=Path("{directory}"), review_after_runs=5)


@pytest.fixture
def replay_in_stack():
    return None


def test_calls(replay):
    for text in os.environ["INNER_CALLS"].split(","):
        httpx.post(replay.addresses["{name}"] + "/v1/call", content=text.encode())


def test_no_calls(replay):
    pass
"""

# What each report of the inner session carries, so a test can read its `user_properties`.
CONFTEST = """
import json
import os


def pytest_runtest_logreport(report):
    properties = [[name, str(value)] for name, value in report.user_properties]
    with open(os.environ["INNER_PROPERTIES"], "a") as out:
        out.write(json.dumps([report.nodeid, properties]) + "\\n")
"""


class Session:
    def __init__(
        self,
        pytester: pytest.Pytester,
        monkeypatch: pytest.MonkeyPatch,
        upstream: FakeUpstream,
        tmp_path: Path,
    ) -> None:
        self.pytester = pytester
        self.monkeypatch = monkeypatch
        self.directory = tmp_path / "cassettes"
        self.properties = tmp_path / "properties.jsonl"
        self.source = INNER.format(
            name=UPSTREAM, url=upstream.url, env=ENV, directory=self.directory
        )
        pytester.makeconftest(CONFTEST)

    def run(self, mode: str, calls: str) -> pytest.RunResult:
        self.monkeypatch.setenv("INNER_CALLS", calls)
        self.monkeypatch.setenv("INNER_PROPERTIES", str(self.properties))
        self.properties.unlink(missing_ok=True)
        return run_session(self.pytester, self.monkeypatch, mode, test_inner=self.source)

    def properties_of(self, name: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for line in self.properties.read_text().splitlines():
            nodeid, properties = json.loads(line)
            if nodeid.endswith(f"::{name}"):
                found.update(dict(properties))
        return found


@pytest.fixture
def session(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    upstream: FakeUpstream,
    tmp_path: Path,
) -> Session:
    return Session(pytester, monkeypatch, upstream, tmp_path)


def test_a_replayed_test_is_labelled_with_its_counts_and_its_outcome_is_unchanged(
    session: Session,
) -> None:
    session.run("record", "a,b,c")

    result = session.run("replay", "a,b,d")

    result.assert_outcomes(passed=2)
    label = session.properties_of("test_calls")["replay"]
    assert "replayed" in label
    assert "2 of 3" in label
    assert "1 live" in label
    summary = [line for line in result.stdout.lines if "test_calls" in line and "2 of 3" in line]
    assert summary, "the terminal summary labels the test"
    assert "  live: call 2: body differs" in result.stdout.lines, "and where the live call differed"


def test_a_test_that_replayed_nothing_carries_no_label(session: Session) -> None:
    session.run("record", "a")

    result = session.run("replay", "a")

    assert "replay" not in session.properties_of("test_no_calls")
    assert not [
        line for line in result.stdout.lines if "test_no_calls" in line and "replayed" in line
    ]


def test_a_recording_run_labels_nothing(session: Session) -> None:
    result = session.run("record", "a,b")

    result.assert_outcomes(passed=2)
    assert "replay" not in session.properties_of("test_calls")


def waiting(session: Session, runs: int) -> str:
    """A cassette of a test that no longer exists, waiting for `runs` runs."""
    held = waiting_cassette("tests/test_gone.py::test_old")
    write_cassette(session.directory, held)
    name = cassette_name(session.directory, held)
    write_state(session.directory, ReplayState(unreviewed_runs={name: runs}))
    return name


def test_a_set_unreviewed_past_the_limit_warns_on_the_next_run_and_fails_nothing(
    session: Session,
) -> None:
    waiting(session, runs=6)

    result = session.run("replay", "a")

    result.assert_outcomes(passed=2)
    assert result.ret == 0
    output = result.stdout.str()
    assert "abk replay review" in output
    assert "warn" in output.lower()


def test_a_set_within_the_limit_does_not_warn_and_each_run_is_counted_in_the_state_file(
    session: Session,
) -> None:
    name = waiting(session, runs=1)
    committed = (session.directory / name).read_bytes()

    result = session.run("replay", "a")

    assert "abk replay review" not in result.stdout.str()
    assert read_state(session.directory).unreviewed_runs[name] == 2
    assert (session.directory / name).read_bytes() == committed


def test_a_replay_run_writes_its_report_beside_the_state_and_ignored(
    session: Session, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    session.run("record", "a,b,c")

    session.run("replay", "a,b,d")

    report = RunReport.model_validate_json((session.directory / REPORT_FILE).read_text())
    by_name = {test.test_id.rsplit("::", 1)[1]: test for test in report.tests}
    assert by_name["test_calls"].hits == 2
    assert len(by_name["test_calls"].misses) == 1
    ignored = git(tmp_path, "check-ignore", "-q", str(session.directory / REPORT_FILE), check=False)
    assert ignored.returncode == 0
