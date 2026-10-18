"""A unit built through the `claude_code` runtime, driven as an operator drives it.

The one parameter carries its runtime tag, `runtime_claude_code`; the ACP variants are added by
a separate change. `abk tick` is the real CLI run as a process, so what is asserted is what an
operator would see: the branch on the remote, the order of its commits, the unit's run log, the
tick's own output arriving while the run works, and what `abk report` says the unit used.

Needs node for the OpenSpec CLI and uv. Only GitHub is faked, at the host's API: a fake server
reached through `ABK_GITHUB_API_URL`, with `gh auth token` the one command left as a script.
Bills on demand and takes minutes, so it is marked with the e2e marker and excluded from the
default suite.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import Field

from agent_build_kit import config
from agent_build_kit.graph.state import Node
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.commit_order import check_structure, classify_paths
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, read_ledger
from tests.factories import git, init_repo, scratch_app
from tests.factories import who_pushed as reflog_and_pushes
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtime_scratch import CLAUDE_CODE_PARAMS, runtime_scratch
from tests.scratch_tick import TickResult, commits_on_unit_branch, run_tick

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "add-marker"
BRANCH = f"spec/{CHANGE}/1"
UNIT_ID = f"{CHANGE}/1"

TASKS = """# Tasks

## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `marker()` in `src/app/marker.py` returns the string `"marked"`.
- [ ] 1.2 Add `marker()` to `src/app/marker.py`.

Acceptance: none — a single function whose own test is its proof
"""


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    planning: Path
    app: Path
    remote: Path
    state: Path
    env: dict[str, str] = Field(repr=False)
    host: FakeGitHub


@pytest.fixture(scope="module")
def github_host() -> Iterator[FakeGitHub]:
    """The fake host, numbering its first pull request 7."""
    with FakeGitHub(first_number=7) as server:
        yield server
        # Checked for every test of the module: a route the fake does not serve
        # fails here, naming it, even when no test looked.
        missed = server.unrouted()
        assert missed == [], f"the forge called routes the fake host does not serve: {missed}"


@pytest.fixture(scope="module")
def scratch_ledger(scratch: Scratch) -> Path:
    """The scratch installation's usage ledger, for the time split of each phase."""
    return scratch.state / LEDGER_NAME


@pytest.fixture(scope="module", params=CLAUDE_CODE_PARAMS)
def scratch(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
    github_host: FakeGitHub,
) -> Iterator[Scratch]:
    """The unit's installation for the runtime parameter, which carries its tag."""
    tmp_path = tmp_path_factory.mktemp("build")
    runtime = runtime_scratch(request.param, tmp_path_factory, lambda command: None)

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    # A bare repository keeps no reflog unless asked: it is what says, when
    # the branch is not the pipeline's, which push put it there.
    git(remote, "config", "core.logAllRefUpdates", "always")

    app = scratch_app(tmp_path / "app")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main")

    planning = init_repo(tmp_path / "planning")
    change = planning / "openspec" / "changes" / CHANGE
    (change / "specs" / "marker").mkdir(parents=True)
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    (change / "proposal.md").write_text(
        "## Why\n\nThe app needs a marker.\n\n## What Changes\n\n- Add `marker()`.\n\n"
        "## Impact\n\n- app: one module.\n"
    )
    (change / "specs" / "marker" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: A marker\nThe app SHALL expose `marker()`.\n\n"
        "#### Scenario: Reading it\n- **WHEN** `marker()` is called\n"
        '- **THEN** it returns "marked"\n'
    )
    (change / "tasks.md").write_text(TASKS)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"{runtime.runtimes_yaml}"
    )
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")

    env = {
        **process_env(github_host, tmp_path / "bin", tmp_path / "gh-calls.txt"),
        **runtime.env,
        "ABK_CONFIG": str(planning / "abk.yaml"),
        "ABK_WORKTREE_ROOT": str(tmp_path / "worktrees"),
    }
    yield Scratch(
        planning=planning,
        app=app,
        remote=remote,
        state=Installation(config.load(planning / "abk.yaml"), planning).state_dir,
        env=env,
        host=github_host,
    )


@pytest.fixture(scope="module")
def built(scratch: Scratch, scratch_ledger: Path) -> tuple[Scratch, TickResult]:
    ticked = run_tick(scratch)
    return scratch, ticked


def pushed_commits(scratch: Scratch, ticked: TickResult) -> list[tuple[str, list[str]]]:
    """The branch on the remote, oldest first: each commit's subject and the
    paths it touched. A branch that never arrived fails with cause hints, the
    tick's own output and the scratch's state, so the failure says where the run stopped."""
    ids = commits_on_unit_branch(scratch, BRANCH, ticked)
    commits: list[tuple[str, list[str]]] = []
    for sha in reversed(ids):
        shown = git(scratch.remote, "show", "--name-only", "--format=@@%s", sha)
        for line in shown.splitlines():
            if line.startswith("@@"):
                commits.append((line[2:], []))
            elif line:
                commits[-1][1].append(line)
    return commits


def pushes_in(log: str) -> list[str]:
    """Every line of the run log that records a `git push`: the agent's tool
    calls and refusals are logged there, the pipeline's own push as `pushed`."""
    return [line for line in log.splitlines() if "git push" in line or " pushed spec/" in line]


def who_pushed(scratch: Scratch) -> str:
    """What says who put the branch on the remote: its reflog there, and each
    push the run log records."""
    return reflog_and_pushes(scratch.remote, BRANCH, pushes_in(run_log(scratch)))


def is_test(path: str) -> bool:
    return classify_paths([path])[path] == "test"


def run_log(scratch: Scratch) -> str:
    logs = sorted((scratch.state / "unit-logs").glob(f"{CHANGE}-01-*.log"))
    return "\n".join(path.read_text() for path in logs)


def test_the_unit_is_built_reviewed_and_pushed_through_the_runtime(
    built: tuple[Scratch, TickResult],
) -> None:
    scratch, ticked = built

    assert ticked.returncode == 0, f"{ticked.output}\n{who_pushed(scratch)}"
    # A Claude run has a usage window to read, so its round logs the start decision. The scratch
    # setup turns the guard off, so the decision's reason (`usage_guard.decide_start`) is the
    # guard-off reason on a line of its own. The banner `GUARD_OFF_LINE` is printed for every
    # runtime, so it is no evidence; only a runtime without a window says it has none.
    assert "has no usage window" not in ticked.output, ticked.output
    assert any(line.endswith("usage guard off (ABK_USAGE_GUARD)") for _, line in ticked.lines), (
        ticked.output
    )
    commits = pushed_commits(scratch, ticked)

    def found() -> str:
        return (
            "commits pushed, oldest first:\n"
            + "\n".join(f"  {subject}: {paths}" for subject, paths in commits)
            + f"\n{who_pushed(scratch)}"
        )

    # Judged as the pipeline judges it: a tests-first commit (stubs allowed),
    # then the implementation.
    checkout = scratch.remote.parent / "order-check"
    shutil.rmtree(checkout, ignore_errors=True)
    git(
        scratch.remote.parent, "clone", "-q", "--branch", BRANCH, str(scratch.remote), str(checkout)
    )
    problems = check_structure(checkout, "origin/main")
    assert problems == [], f"{problems}\n{found()}"
    first_test = next(
        (i for i, (_, paths) in enumerate(commits) if any(is_test(p) for p in paths)), None
    )
    assert first_test is not None, f"no commit touches a test file\n{found()}"
    assert any("src/app/marker.py" in paths for _, paths in commits[first_test + 1 :]), (
        f"no commit after the tests implements src/app/marker.py\n{found()}"
    )
    log_lines = run_log(scratch).splitlines()
    assert any(f"{Node.REVIEW}: review round" in line for line in log_lines), (
        log_lines,
        ticked.output,
    )
    assert any("in review: PR #7" in line for line in log_lines), (log_lines, ticked.output)
    assert scratch.host.requests("POST", "/repos/example/app/pulls"), (
        f"no pull request was opened\n{ticked.output}"
    )


def test_the_pipeline_alone_pushed_and_only_what_review_approved(
    built: tuple[Scratch, TickResult],
) -> None:
    scratch, ticked = built

    assert ticked.returncode == 0, f"{ticked.output}\n{who_pushed(scratch)}"
    pushed_commits(scratch, ticked)
    log = run_log(scratch)
    tip = git(scratch.remote, "rev-parse", BRANCH).strip()
    approved = [line.rsplit(" ", 1)[-1] for line in log.splitlines() if "review approved " in line]
    # Who pushed is judged from the remote, not from what the log says the agent
    # tried: every update its reflog records is one of the pipeline's own pushes.
    pipeline_pushed = re.findall(rf" pushed {re.escape(BRANCH)} at ([0-9a-f]+)", log)
    reflog = git(scratch.remote, "reflog", "show", f"refs/heads/{BRANCH}", "--format=%H").split()
    assert pipeline_pushed, f"{log}\n{ticked.output}"
    assert len(reflog) == len(pipeline_pushed), f"{who_pushed(scratch)}\n{ticked.output}"
    for sha in reflog:
        assert any(sha.startswith(seen) for seen in pipeline_pushed), (
            f"{who_pushed(scratch)}\n{ticked.output}"
        )
    assert tip[:9] in approved, (
        f"the branch is at {tip[:9]}, review approved {approved}\n{ticked.output}"
    )
    # None rewritten away: each commit the pipeline pushed is still in the
    # history of the tip.
    for sha in reflog:
        merged = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, tip], cwd=scratch.remote, check=False
        )
        assert merged.returncode == 0, (
            f"{sha[:9]} was pushed and is no longer in the branch\n{ticked.output}"
        )


def test_progress_is_visible_while_the_run_works(built: tuple[Scratch, TickResult]) -> None:
    _, ticked = built

    # The graph's own lines are `<unit id>: <node>: <message>`; the agent's
    # progress is `<unit id>:` followed by the runtime's two-space-indented line.
    nodes = "|".join(re.escape(node.value) for node in Node)
    own = re.compile(rf"^\[[\d:]+\] {re.escape(UNIT_ID)}: ({nodes}): ")
    progress = re.compile(rf"^\[[\d:]+\] {re.escape(UNIT_ID)}:   \S")
    steps = [
        (at, i, match.group(1))
        for i, (at, line) in enumerate(ticked.lines)
        if (match := own.match(line))
    ]
    first = next(
        (n for n, (_, _, node) in enumerate(steps) if node in (Node.TESTS, Node.IMPLEMENT)), None
    )
    assert first is not None, ticked.output
    # The node's own lines (`started`, its step) belong to it: the window ends
    # where the next node's first line begins.
    after = next((s for s in steps[first:] if s[2] != steps[first][2]), None)
    assert after is not None, ticked.output
    window = ticked.lines[steps[first][1] + 1 : after[1]]
    arrivals = [at for at, line in window if progress.match(line)]
    next_step = after[0]
    # Lines that arrive as the agent works, not all together when its turn ends.
    assert len(arrivals) >= 3, (
        f"agent progress lines in the step: {len(arrivals)}\n{window}\n{ticked.output}"
    )
    assert arrivals[0] < next_step - 5, (
        f"the agent's progress arrived only as its run ended\n{ticked.output}"
    )


# A run log line that begins an agent call names its model in brackets; these
# are the node messages that start one.
AGENT_STEP = re.compile(
    r"\b(?:tests|implement|fix_checks|review|rework): "
    r"(?:write the tests|implement|fix the failing checks|review round \d+"
    r"|address review round \d+|rework from feedback) \("
)
SOURCES = {"reported", "gateway", "estimated", "none"}


def abk_report(scratch: Scratch, *args: str) -> str:
    """`abk report` for the unit, as an operator runs it."""
    done = subprocess.run(
        [str(Path(sys.executable).parent / "abk"), "report", "--unit", UNIT_ID, *args],
        cwd=scratch.planning,
        env=scratch.env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def calls_of(row: dict) -> int:
    return row["measured"]["calls"] + row["estimated"]["calls"]


def summed(values: list[int | None]) -> int | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def test_the_report_has_one_agent_record_per_call_in_the_run_log(
    built: tuple[Scratch, TickResult],
) -> None:
    scratch, ticked = built

    assert ticked.returncode == 0, ticked.output
    pushed_commits(scratch, ticked)
    log = run_log(scratch)
    calls = [line for line in log.splitlines() if AGENT_STEP.search(line)]
    assert calls, f"the run log shows no agent call:\n{log}\n{ticked.output}"
    report = json.loads(abk_report(scratch, "--by", "node", "--json", "--include-estimates"))
    assert calls_of(report["total"]) == len(calls), f"{report['rows']}\n{calls}\n{ticked.output}"
    assert sum(calls_of(row) for row in report["rows"]) == len(calls), ticked.output


def test_the_report_totals_equal_the_ledger_and_name_each_figures_source(
    built: tuple[Scratch, TickResult],
) -> None:
    scratch, ticked = built

    assert ticked.returncode == 0, ticked.output
    records = [r for r in read_ledger(scratch.state / LEDGER_NAME) if r.unit == UNIT_ID]
    assert records, f"the ledger holds no record of the unit's calls\n{ticked.output}"
    report = json.loads(abk_report(scratch, "--by", "unit", "--json", "--include-estimates"))
    [row] = report["rows"]
    assert row["key"] == UNIT_ID, ticked.output
    measured = row["measured"]

    assert measured["calls"] == len(records), ticked.output
    assert measured["input_tokens"] == summed([r.input_tokens for r in records]), ticked.output
    assert measured["output_tokens"] == summed([r.output_tokens for r in records]), ticked.output
    assert row["agent_ms"] == summed([r.duration_ms for r in records]), ticked.output
    assert report["total"]["measured"]["input_tokens"] == measured["input_tokens"], ticked.output
    # Each figure's source is shown: the row names every source its calls had,
    # in the JSON and in the table.
    assert set(row["sources"]) == {r.usage_source for r in records}, ticked.output
    assert set(row["sources"]) <= SOURCES, ticked.output
    table = abk_report(scratch)
    assert all(source in table for source in row["sources"]), f"{table}\n{ticked.output}"
