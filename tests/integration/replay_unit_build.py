"""The build that `test_replay_unit.py` runs three times, as its own pytest session.

Not collected by the suite (the name does not start with `test_`): the acceptance test starts
`pytest` on this file with the replay plugin and a mode, three times over the same cassette
directory, so the test id and so the cassettes' place stay the same between the steps.

One scratch unit is built by `abk tick` with the Claude Code agent,
behind the replay proxy: the package index and the model endpoint are handed the proxy's
addresses. The scratch is deterministic where the fixtures can make it so: it lives at a fixed
place, every commit has the same identity and date, and the agent's home is fixed too, because
the driver gives each session the same `--basetemp`, which `agent_home` makes it under.
What the driver passes in:

- `ABK_REPLAY_UNIT_ROOT`: where the scratch lives, emptied at the start of each build
- `ABK_REPLAY_UNIT_CASSETTES`: the cassette directory
- `ABK_REPLAY_UNIT_MARKER`: the string `marker()` is to return, the task text the third step edits
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from agent_build_kit.config import ReplayConfig, ReplayUpstream
from agent_build_kit.replay.models import Rule, UpstreamKind
from tests.forges.github_server import FakeGitHub
from tests.marker_scratch import CHANGE, build_scratch
from tests.replay.proxy import ReplayProxy
from tests.runtime_scratch import runtime_scratch
from tests.scratch_tick import commits_on_unit_branch, register_scratch, run_tick

ROOT = "ABK_REPLAY_UNIT_ROOT"
CASSETTES = "ABK_REPLAY_UNIT_CASSETTES"
MARKER = "ABK_REPLAY_UNIT_MARKER"
DRIVER_ENVIRONMENT = (ROOT, CASSETTES, MARKER)


def missing_environment() -> list[str]:
    """The names of the driver's variables that are not set."""
    return [name for name in DRIVER_ENVIRONMENT if not os.environ.get(name)]


# This is a helper the driver runs by id, not a test of the suite: without the driver's
# environment it is skipped, and the reason names what is missing.
pytestmark = [
    # An e2e test in its own session: it starts a real agent and takes minutes, so it is under
    # the e2e time limit and not the default one.
    pytest.mark.local_stack,
    pytest.mark.skipif(
        bool(missing_environment()),
        reason=f"run by test_replay_unit.py; not set: {', '.join(missing_environment())}",
    ),
]

# The one normalisation: the session id the agent puts in `metadata.user_id`, a JSON string
# inside the JSON body, so its quotes stand escaped. The text before the id is kept and no other
# field is touched. Anything else that varies is left to make a call go live.
SESSION_RULE = Rule(
    pattern=(
        r'(session_id\\"\s*:\s*\\")'
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    ),
    placeholder=r"\g<1>SESSION",
)

# The upstreams the unit's calls go through. The package index is deterministic; the model
# endpoint is the one the agent may or may not honour, which the report then shows.
INDEX = ReplayUpstream(
    name="index",
    url="https://pypi.org/simple",
    kind=UpstreamKind.deterministic,
    env=["UV_DEFAULT_INDEX"],
)
MODEL = ReplayUpstream(
    name="model",
    url="https://api.anthropic.com",
    kind=UpstreamKind.llm,
    env=["ANTHROPIC_BASE_URL"],
)

# The same identity and date for every commit, so a commit's hash is the same on every run.
IDENTITY = {
    "GIT_AUTHOR_NAME": "replay",
    "GIT_AUTHOR_EMAIL": "replay@example.invalid",
    "GIT_AUTHOR_DATE": "2030-01-01T09:00:00+0000",
    "GIT_COMMITTER_NAME": "replay",
    "GIT_COMMITTER_EMAIL": "replay@example.invalid",
    "GIT_COMMITTER_DATE": "2030-01-01T09:00:00+0000",
}

TASKS = """# Tasks

## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"{marker}"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof
"""


REPO = Path(__file__).resolve().parents[2]


def session_argv(basetemp: Path) -> list[str]:
    """The command that runs this file as its own pytest session, which the driver runs from
    `REPO`. `-o addopts=` is what keeps the repository's `-m 'not local_stack'` from deselecting
    the build; the same `basetemp` for every session puts the agent's home at the same path."""
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "tests.replay.plugin",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        f"--basetemp={basetemp}",
        str(Path(__file__).resolve()),
    ]


@pytest.fixture
def replay_rules() -> list[Rule]:
    return [SESSION_RULE]


@pytest.fixture
def replay_config() -> ReplayConfig:
    return ReplayConfig(upstreams=[INDEX, MODEL], directory=Path(os.environ[CASSETTES]))


def test_the_unit_is_built(
    replay: ReplayProxy,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in IDENTITY.items():
        monkeypatch.setenv(name, value)
    root = Path(os.environ[ROOT])
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    marker = os.environ[MARKER]
    runtime = runtime_scratch("claude_code", tmp_path_factory, lambda command: None)

    with FakeGitHub(first_number=7) as host:
        scratch = build_scratch(
            root,
            host,
            runtime,
            tasks=TASKS.format(marker=marker),
            marker=marker,
            extra_env=replay.environment(),
        )
        register_scratch(scratch)
        ticked = run_tick(scratch)

    assert ticked.returncode == 0, ticked.output
    assert commits_on_unit_branch(scratch, f"spec/{CHANGE}/1", ticked), ticked.output
