"""Replay proven on a real unit: a live pass, a replay of it, and a changed input going live.

One scratch unit (`replay_unit_build.py`) is built three times by `abk tick` with the agent named
by `ABK_ACCEPTANCE_ACP_COMMAND`, each time as a pytest session with the replay plugin over the
same cassette directory: in `record` mode, in `replay` mode with nothing changed, and in `replay`
mode with the task text edited. What is asserted is read from what the sessions leave: the
cassettes, `report.json` and the terminal summary.

The package index is asserted first, since it is the upstream whose requests are the same on every
run. The model endpoint is reported (its hit rate is printed and recorded as a test property) and
no assertion is loosened to obtain a hit: an agent that does not honour the endpoint it is handed
makes no model call to replay, and zero model hits is a finding. Bills on demand and takes
minutes, so it carries the e2e marker and is excluded from the default suite.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.model import Frozen
from agent_build_kit.replay.models import Cassette, ReplayMode, UpstreamKind
from agent_build_kit.replay.report import ReplayedTest, RunReport
from agent_build_kit.replay.state import REPORT_FILE
from agent_build_kit.replay.store import cassette_name, read_cassettes
from tests.integration import replay_unit_build as build
from tests.replay.support import replayed_cassettes

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

# Each scenario drives the protocol runtime only: how Claude Code is pointed at the proxy is
# unverified (docs/agent-runtimes.md), so there is no claude_code variant yet.
POINTED_AT_ACP_ONLY = "the proxy is pointed at the protocol agent only"
ACP_ONLY_REASONS = {
    "test_a_live_pass_in_record_mode_is_promoted_to_cassettes": POINTED_AT_ACP_ONLY,
    "test_an_unchanged_rerun_replays_the_deterministic_calls_and_is_labelled": POINTED_AT_ACP_ONLY,
    "test_an_edited_task_sends_exactly_the_changed_calls_live": POINTED_AT_ACP_ONLY,
}
TEST_ID = "tests/integration/replay_unit_build.py::test_the_unit_is_built"
LABEL = re.compile(r"replayed: (\d+) of (\d+) external calls replayed, (\d+) live")
RECORDED_MARKER = "marked"
EDITED_MARKER = "marked again"


class Step(Frozen):
    """One session of the build: how it ended, what it printed, and the cassettes either side."""

    directory: Path
    returncode: int
    output: str
    before: list[Cassette]
    after: list[Cassette]
    report: RunReport | None

    @property
    def test(self) -> ReplayedTest | None:
        tests = self.report.tests if self.report else []
        found = [test for test in tests if test.test_id == TEST_ID]
        return found[-1] if found else None


def kinds(cassettes: list[Cassette], kind: UpstreamKind) -> list[Cassette]:
    return [c for c in cassettes if c.kind is kind and c.test_id == TEST_ID]


def run_step(mode: ReplayMode, marker: str, directory: Path, root: Path) -> Step:
    before = read_cassettes(directory) if directory.exists() else []
    env = {
        **os.environ,
        "ABK_REPLAY_MODE": mode.value,
        build.ROOT: str(root),
        build.CASSETTES: str(directory),
        build.MARKER: marker,
    }
    ran = subprocess.run(
        build.session_argv(root.parent / "abk-replay-unit-tmp"),
        cwd=build.REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    written = directory / REPORT_FILE
    return Step(
        directory=directory,
        returncode=ran.returncode,
        output=ran.stdout + ran.stderr,
        before=before,
        after=read_cassettes(directory) if directory.exists() else [],
        report=RunReport.model_validate_json(written.read_text()) if written.exists() else None,
    )


# The three builds run in order over one cassette directory and one fixed scratch place. Each is
# its own fixture, so the test that first needs a build waits for that build alone under the
# e2e limit, not for the three together.
@pytest.fixture(scope="module")
def cassettes(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cassettes")


@pytest.fixture(scope="module")
def scratch_root() -> Path:
    return Path(tempfile.gettempdir()) / "abk-replay-unit"


@pytest.fixture(scope="module")
def recorded_step(cassettes: Path, scratch_root: Path) -> Step:
    return run_step(ReplayMode.record, RECORDED_MARKER, cassettes, scratch_root)


@pytest.fixture(scope="module")
def replayed_step(recorded_step: Step, cassettes: Path, scratch_root: Path) -> Step:
    return run_step(ReplayMode.replay, RECORDED_MARKER, cassettes, scratch_root)


@pytest.fixture(scope="module")
def edited_step(replayed_step: Step, cassettes: Path, scratch_root: Path) -> Step:
    return run_step(ReplayMode.replay, EDITED_MARKER, cassettes, scratch_root)


@pytest.mark.runtime_acp
def test_a_live_pass_in_record_mode_is_promoted_to_cassettes(recorded_step: Step) -> None:
    record = recorded_step

    assert record.returncode == 0, record.output
    # The deterministic upstream first: no call reaching it means the index was never pointed at.
    assert kinds(record.after, UpstreamKind.deterministic), (
        f"no call reached the package index through the proxy\n{record.output}"
    )
    assert record.after, record.output


@pytest.mark.runtime_acp
def test_an_unchanged_rerun_replays_the_deterministic_calls_and_is_labelled(
    recorded_step: Step, replayed_step: Step, record_property: Callable[[str, object], None]
) -> None:
    record, replay = recorded_step, replayed_step

    assert replay.returncode == 0, replay.output
    recorded = kinds(record.after, UpstreamKind.deterministic)
    assert recorded, record.output
    test = replay.test
    assert test is not None, replay.output
    by_key = {c.key: c for c in replay.after}
    missed = [by_key[miss.key] for miss in test.misses if miss.key in by_key]
    # Every call to the package index with an identical key was replayed: none went live.
    assert [c for c in missed if c.kind is UpstreamKind.deterministic] == [], replay.output
    # Each recorded index call was asked for again, not only counted among the model's hits.
    unused = [c for c in recorded if cassette_name(replay.directory, c) in test.unused]
    assert unused == [], replay.output
    assert test.hits >= len(recorded), replay.output
    label = LABEL.search(replay.output)
    assert label is not None, f"the test is not labelled replayed\n{replay.output}"
    assert tuple(map(int, label.groups())) == (
        test.hits,
        test.hits + len(test.misses),
        len(test.misses),
    )
    # The model: reported, never asserted to hit. A recorded call was replayed only when this
    # session asked for its cassette and it was not too old to answer.
    recorded_model = kinds(record.after, UpstreamKind.llm)
    replayed_model = replayed_cassettes(recorded_model, replay.directory, test)
    record_property("model_calls_recorded", len(recorded_model))
    record_property("model_calls_replayed", len(replayed_model))
    print(f"model hit rate: {len(replayed_model)} of {len(recorded_model)} recorded calls")
    assert replay.report is not None
    assert replay.report.billed_calls_avoided <= len(replayed_model)


@pytest.mark.runtime_acp
def test_an_edited_task_sends_exactly_the_changed_calls_live(edited_step: Step) -> None:
    edited = edited_step

    assert edited.returncode == 0, edited.output
    test = edited.test
    assert test is not None, edited.output
    assert test.misses, (
        "editing the task text changed no recorded call: the agent's model calls do not go "
        f"through the proxy\n{edited.output}"
    )
    before = {c.key for c in edited.before}
    after = {c.key: c for c in edited.after}
    live = {miss.key for miss in test.misses}
    # Only the model's calls depend on the task text; the package index is asked the same.
    assert all(after[key].kind is UpstreamKind.llm for key in live), edited.output
    # A new cassette for each call that went live, and for no other.
    assert {key for key in after if key not in before} == live
    for miss in test.misses:
        assert miss.difference, edited.output
        assert miss.difference in edited.output
        # The cassette the live call replaced at its index is held for review, not deleted.
        for old in (c for c in edited.before if c.test_id == TEST_ID):
            if old.call_index == miss.call_index and old.key != miss.key:
                kept = next((c for c in edited.after if c.key == old.key), None)
                assert kept is not None, f"the superseded cassette was deleted\n{edited.output}"
                # Superseded, not merely unasked: the reason names the live call that replaced it.
                assert kept.needs_review, edited.output
                assert kept.review_reason.startswith("superseded by a live call"), (
                    f"{kept.review_reason!r}\n{edited.output}"
                )
