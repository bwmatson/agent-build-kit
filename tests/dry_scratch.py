"""The scratch app and planning repos the dry-guidance acceptance tests build in.

`dry_app` is `scratch_app` plus one helper with a distinctive body. Each case gets its own
copy and its own planning repo, so no case sees another's work.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import Field

from agent_build_kit import config
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from tests.acp_recorder import wrapped
from tests.dry_checks import diff_definitions
from tests.factories import commit_files, git, init_repo, scratch_app
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtime_scratch import runtime_scratch
from tests.scratch_tick import branch_on_remote, commits_on_unit_branch, register_scratch, run_tick

TICK_TIMEOUT = 25 * 60
LOG_TAIL = 6000

# The key literals the cases count: `slugify`'s character class, and what the share case's
# formatting is told to do to its prefix. Each occurs once in the tree the case starts from.
SQUEEZE = "[^a-z0-9]+"
UPPER = ".upper()"

SLUGIFY = """\
import re


def slugify(text):
    lowered = text.lower()
    squeezed = re.sub(r"@SQUEEZE@", "-", lowered)
    return squeezed.strip("-")
"""

SLUGIFY = SLUGIFY.replace("@SQUEEZE@", SQUEEZE)

SLUGIFY_TESTS = """\
from app.text import slugify


def test_it_squeezes_every_run_of_other_characters_into_one_hyphen():
    assert slugify("Hello,   World!") == "hello-world"


def test_it_trims_hyphens_from_both_ends():
    assert slugify("  --Hi--  ") == "hi"
"""

PAGE_TESTS = """\
from app.pages import page_path


def test_a_page_lives_under_pages_named_for_its_title():
    assert page_path("Hello,   World!") == "pages/hello-world.md"
"""

PAGES_DUPLICATE = """\
import re


def title_slug(title):
    lowered = title.lower()
    squeezed = re.sub(r"@SQUEEZE@", "-", lowered)
    return squeezed.strip("-")


def page_path(title):
    return "pages/" + title_slug(title) + ".md"
"""

PAGES_CLEAN = """\
from app.text import slugify


def page_path(title):
    return "pages/" + slugify(title) + ".md"
"""

PAGES_DUPLICATE = PAGES_DUPLICATE.replace("@SQUEEZE@", SQUEEZE)

REUSE_TASKS = """\
## 1. [app] [unit-test] Page paths

- [ ] 1.1 Test: `page_path(title)` in `src/app/pages.py` returns `pages/<slug>.md`, where the slug
      is the title in lower case with every run of other characters squeezed into one hyphen.
- [ ] 1.2 Add `title_slug(title)` to `src/app/pages.py`, which squeezes a title into a slug, and
      `page_path(title)`, which uses it.

Acceptance: none — two small functions whose own tests are their proof
"""

# The review cases seed their branches, so their task names only the behaviour: a task that
# named `title_slug` would make the clean branch, which has none, deviate from its spec.
REVIEW_TASKS = """\
## 1. [app] [unit-test] Page paths

- [ ] 1.1 Test: `page_path(title)` in `src/app/pages.py` returns `pages/<slug>.md`, where the slug
      is the title in lower case with every run of other characters squeezed into one hyphen.
- [ ] 1.2 Add `page_path(title)` to `src/app/pages.py`.

Acceptance: none — one small function whose own test is its proof
"""

GENERALIZE_TASKS = """\
## 1. [app] [unit-test] File stems

- [ ] 1.1 Test: `file_stem(title)` in `src/app/files.py` squeezes the title as its slug is
      squeezed, but joins words with underscores and keeps dots, so `file_stem("Report v1.2!")`
      is `report_v1.2`.
- [ ] 1.2 Add `file_stem(title)` to `src/app/files.py`.

Acceptance: none — one small function whose own test is its proof
"""

SHARE_TASKS = """\
## 1. [app] [unit-test] Labels

- [ ] 1.1 Test: `invoice_label(prefix, number)` in `src/app/invoices.py` and
      `receipt_label(prefix, number)` in `src/app/receipts.py` each return the prefix in upper
      case, a hyphen, and the number zero-padded to four digits, so `invoice_label("inv", 7)`
      is `INV-0007`.
- [ ] 1.2 Add `invoice_label` and `receipt_label`.

Acceptance: none — two small functions whose own tests are their proof
"""

# Each case: the change it builds, its tasks, and the branch seeded for the review cases.
CASES = {
    "reuse": ("add-page-path", REUSE_TASKS, ""),
    "generalize": ("add-file-stem", GENERALIZE_TASKS, ""),
    "share": ("add-labels", SHARE_TASKS, ""),
    "duplicate": ("add-page-path", REVIEW_TASKS, "duplicate"),
    "clean": ("add-page-path", REVIEW_TASKS, "clean"),
}


@contextmanager
def fake_host() -> Iterator[FakeGitHub]:
    """The fake code host, numbering its first pull request 7."""
    with FakeGitHub(first_number=7) as server:
        yield server


def _has_branch(repo: Path, branch: str) -> bool:
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", branch], cwd=repo, capture_output=True
    )
    return found.returncode == 0


class DryRun(Frozen):
    """A case after its one tick."""

    change: str
    branch: str
    app: Path
    remote: Path
    planning: Path
    state: Path
    record: Path
    env: dict[str, str] = Field(repr=False)
    tick_output: str = ""

    @property
    def scratch(self) -> DryRun:
        """What the failure dump reads of a test that takes this run as a fixture value: the run
        is its own scratch, so every test of a module-scoped case prints the SCRATCH STATE
        section, not only the one that set the fixture up."""
        return self

    @property
    def repo(self) -> Path:
        """Where the branch is: the remote once the unit pushed it, else the local app, which
        holds a seeded branch and what a held or failed tick left."""
        return self.remote if branch_on_remote(self, self.branch) else self.app


def dry_app(path: Path) -> Path:
    """`scratch_app` plus `slugify` in `src/app/text.py` and its tests, committed on `main`."""
    app = scratch_app(path)
    commit_files(app, "slugify", {"src/app/text.py": SLUGIFY, "tests/test_text.py": SLUGIFY_TESTS})
    return app


def seed_branch(app: Path, change: str, *, duplicate: bool) -> str:
    """A local branch `spec/<change>/1` holding a tests commit and an implementation commit:
    one that re-implements `slugify` under a new name, or one that calls it."""
    branch = f"spec/{change}/1"
    git(app, "checkout", "-q", "-b", branch, "main")
    commit_files(app, "tests", {"tests/test_pages.py": PAGE_TESTS})
    pages = PAGES_DUPLICATE if duplicate else PAGES_CLEAN
    commit_files(app, "implementation", {"src/app/pages.py": pages})
    git(app, "checkout", "-q", "main")
    return branch


def _planning(root: Path, app: Path, change: str, tasks: str, command: list[str]) -> Path:
    planning = init_repo(root / "planning")
    folder = planning / "openspec" / "changes" / change
    (folder / "specs" / "dry").mkdir(parents=True)
    (planning / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    (folder / "proposal.md").write_text(
        "## Why\n\nThe app needs the function.\n\n## What Changes\n\n- Add it.\n\n"
        "## Impact\n\n- app: one module.\n"
    )
    (folder / "specs" / "dry" / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: The function\nThe app SHALL provide it.\n\n"
        "#### Scenario: Calling it\n- **WHEN** it is called\n- **THEN** it returns the value\n"
    )
    (folder / "tasks.md").write_text("# Tasks\n\n" + tasks)
    (planning / "abk.yaml").write_text(
        f"repos:\n  app:\n    path: {app}\n    slug: example/app\n"
        "    profile: python-uv\n    languages: [python]\n"
        f"runtimes:\n  acp:\n    command: {json.dumps(command)}\n"
        "limits:\n  max_review_rounds: 1\n"
    )
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")
    return planning


def _log(state: Path, change: str) -> str:
    logs = sorted((state / "unit-logs").glob(f"{change}-01-*.log"))
    return "\n".join(path.read_text() for path in logs)


@contextmanager
def ticked_case(
    tmp_path_factory: pytest.TempPathFactory,
    github: FakeGitHub,
    case: str,
) -> Iterator[DryRun]:
    """Builds `case` ("reuse", "generalize", "share", "duplicate" or "clean") in its own scratch
    app and planning repo, the real agent command wrapped by the recorder, ticks once with
    `max_review_rounds` 1 under `TICK_TIMEOUT`, and yields what is left. Fails, never skips,
    when no agent command is set."""
    change, tasks, seed = CASES[case]
    runtime = runtime_scratch("acp", tmp_path_factory, lambda command: None)
    root = tmp_path_factory.mktemp(f"dry-{case}")
    remote = root / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    app = dry_app(root / "app")
    git(app, "remote", "add", "origin", str(remote))
    git(app, "push", "-q", "origin", "main")
    if seed:
        seed_branch(app, change, duplicate=seed == "duplicate")
    record = root / "agent-lines.jsonl"
    planning = _planning(root, app, change, tasks, wrapped(record, runtime.command))
    run = DryRun(
        change=change,
        branch=f"spec/{change}/1",
        app=app,
        remote=remote,
        planning=planning,
        state=Installation(config.load(planning / "abk.yaml"), planning).state_dir,
        record=record,
        env={
            **process_env(github, root / "bin", root / "gh-calls.txt"),
            **runtime.env,
            "ABK_CONFIG": str(planning / "abk.yaml"),
            "ABK_WORKTREE_ROOT": str(root / "worktrees"),
        },
    )
    register_scratch(run)
    try:
        ticked = run_tick(run, timeout=TICK_TIMEOUT)
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"the tick of {case} ran past {TICK_TIMEOUT}s\n{_log(run.state, change)[-LOG_TAIL:]}"
        )
    if not _has_branch(app, run.branch):
        # On neither repository: fails with the tick's output and the scratch's state.
        commits_on_unit_branch(run, run.branch, ticked)
    yield run.model_copy(update={"tick_output": ticked.output})


def old_tests_pass(run: DryRun) -> str:
    """Runs `main`'s tests against the branch's source; an empty string when they pass, else
    the output."""
    checkout = run.planning.parent / "old-tests"
    subprocess.run(["git", "clone", "-q", str(run.repo), str(checkout)], check=True)
    git(checkout, "checkout", "-q", run.branch)
    git(checkout, "checkout", "-q", "origin/main", "--", "tests/test_text.py")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_text.py", "-q", "-p", "no:cacheprovider"],
        cwd=checkout,
        capture_output=True,
        text=True,
    )
    return "" if result.returncode == 0 else result.stdout + result.stderr


def review_findings(run: DryRun) -> tuple[dict, ...]:
    """The unit's `last_findings`, read from its thread in the checkpoint store."""

    async def look() -> tuple[dict, ...]:
        async with open_checkpointer(unit_graphs_path(run.state)) as saver:
            position = await thread_position(saver, f"{run.change}/1")
            return () if position.state is None else position.state.last_findings

    return asyncio.run(look())


def evidence(run: DryRun) -> str:
    """What a failure message carries: the diff, the definitions counted as added, and the tail
    of the agent's transcript."""
    repo = run.repo
    try:
        diff = git(repo, "diff", f"main...{run.branch}")
        added = [(d.path, d.name) for d in diff_definitions(repo, "main", run.branch).added]
    except subprocess.CalledProcessError as error:
        diff = f"(no branch {run.branch} to diff: {error.stderr.strip()})"
        added = []
    return (
        f"--- diff main...{run.branch} ---\n{diff}\n"
        f"--- definitions counted as added ---\n{added}\n"
        "--- tick output and unit log, tail ---\n"
        f"{(run.tick_output + _log(run.state, run.change))[-LOG_TAIL:]}"
    )
