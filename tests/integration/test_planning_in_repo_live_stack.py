"""A scratch installation whose planning repo is its own code repo, driven the way a person and
the timers would drive it, and the person's working copy untouched throughout.

The repository is `app`: a bare origin, a working copy on a feature branch with an uncommitted
source edit, and an `abk.yaml` that lists the repository at `.` on the local forge. Every command
is the real `abk` run as a process, in a home directory of its own so the timers' units and the
pipeline worktree land under the temporary directory. The agent is the scripted one the ACP
adapter's tests use, run over stdio, so nothing here bills; the policy hook is the real hook
process. Only the planning commit is made in-process, through the function chat uses.

The tests share one scratch repository, and a test that needs another's effect (the install, the
landed and archived change) asks for it through a module-scoped fixture that makes it once, so any
test runs alone or in any order.

Needs node for the OpenSpec CLI and uv. Marked `local_stack` and excluded from the default suite.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import Field

import agent_build_kit
from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.attach import commit_planning
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED
from tests.factories import commit_files, git, stored_unit
from tests.planning_worktree_support import InRepo, publish_elsewhere, working_copy_of
from tests.runtimes import acp_agent

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

CHANGE = "feature"
SOURCE = "src/main.py"
EDIT = "# uncommitted, the person's own\n"
UNITS = '{"units": []}\n'
ABK = str(Path(sys.executable).parent / "abk")
SYNC_STOPPED = "planning sync stopped:"

TASKS = """# Tasks

## 1. [app] [unit-test] Add the marker

- [ ] 1.1 Test: `marker()` returns the string `"marked"`.

Acceptance: none — a single function whose own test is its proof
"""
PROPOSAL = (
    "## Why\n\nThe app needs a marker.\n\n## What Changes\n\n- Add `marker()`.\n\n"
    "## Impact\n\n- app\n"
)
SPEC = (
    "## ADDED Requirements\n\n### Requirement: A marker\nThe app SHALL expose `marker()`.\n\n"
    '#### Scenario: Reading it\n- **WHEN** `marker()` is called\n- **THEN** it returns "marked"\n'
)


def change_files(name: str, *, done: bool = False) -> dict[str, str]:
    return {
        f"openspec/changes/{name}/proposal.md": PROPOSAL,
        f"openspec/changes/{name}/tasks.md": TASKS.replace("[ ]", "[x]" if done else "[ ]"),
        f"openspec/changes/{name}/specs/{name}/spec.md": SPEC,
    }


class Ran(Frozen):
    returncode: int
    output: str


class Standing(Frozen):
    """What a person sees of the working copy: where it is, what is staged and what is edited."""

    branch: str
    head: str
    index: str
    status: str
    diff: str
    edited: str


class Scratch(Frozen):
    model_config = {"arbitrary_types_allowed": True}

    base: Path
    setup: InRepo
    home: Path
    record: Path
    before: Standing
    env: dict[str, str] = Field(repr=False)

    @property
    def worktree(self) -> Path:
        """Where `abk install-timers` puts the pipeline worktree: the repository's name under the
        data directory of the home it ran in."""
        return self.home / ".local" / "share" / "app" / "planning"

    @property
    def origin(self) -> Path:
        assert self.setup.origin is not None
        return self.setup.origin

    @property
    def working_copy(self) -> Path:
        return self.setup.working_copy


def abk(scratch: Scratch, *args: str, cwd: Path, config_file: Path | None = None) -> Ran:
    """The real `abk` as a process, `--config` naming `config_file` when given."""
    argv = [ABK, *(["--config", str(config_file)] if config_file else []), *args]
    run = subprocess.run(
        argv, cwd=cwd, env=scratch.env, capture_output=True, text=True, timeout=1800
    )
    return Ran(returncode=run.returncode, output=run.stdout + run.stderr)


def in_pipeline(scratch: Scratch, *args: str) -> Ran:
    """`abk` in the pipeline worktree, through its own config, as a unit's run would."""
    return abk(scratch, *args, cwd=scratch.worktree, config_file=scratch.worktree / "abk.yaml")


def code_ran(scratch: Scratch) -> Path:
    """The package file the `abk` interpreter imports from the pipeline worktree, with the
    environment the tick gets: the code a tick there runs."""
    shebang = Path(ABK).read_text().splitlines()[0].removeprefix("#!")
    run = subprocess.run(
        [shebang, "-c", "import agent_build_kit; print(agent_build_kit.__file__)"],
        cwd=scratch.worktree,
        env=scratch.env,
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(run.stdout.strip()).resolve()


def untimed(ran: Ran) -> list[str]:
    """The output's lines without the `[hh:mm:ss]` the log prefixes them with."""
    return [line.split("] ", 1)[-1] for line in ran.output.splitlines()]


def standing(working_copy: Path) -> Standing:
    return Standing(
        branch=git(working_copy, "rev-parse", "--abbrev-ref", "HEAD"),
        head=git(working_copy, "rev-parse", "HEAD"),
        index=git(working_copy, "ls-files", "-s"),
        status=git(working_copy, "status", "--porcelain=v1", "--untracked-files=all"),
        diff=git(working_copy, "diff", "HEAD"),
        edited=(working_copy / SOURCE).read_text(),
    )


def assert_untouched(scratch: Scratch) -> None:
    assert standing(scratch.working_copy) == scratch.before, "the working copy was changed"
    assert scratch.before.branch == "feature-work"
    assert scratch.before.edited.endswith(EDIT)


def script(scratch: Scratch, actions: list[dict] | None = None) -> None:
    """The scripted agent's next actions, in the file its command already names."""
    acp_agent.command(scratch.record, act=actions or [])


def abk_yaml(scratch_command: list[str]) -> str:
    """The installation's file: the repository at `.` on the local forge, the scripted agent as
    the ACP runtime. Written as JSON, which is YAML."""
    return json.dumps(
        {
            "repos": {
                "app": {
                    "path": ".",
                    "slug": "example/app",
                    "forge": "local",
                    "profile": "python-uv",
                    "languages": ["python"],
                    "deploy": {"rules": [{"prefix": "src/", "run": [["true"]]}]},
                }
            },
            "runtimes": {"acp": {"command": scratch_command}},
            "planning": {"publish": "direct"},
        },
        indent=2,
    )


def write_usage_cache(home: Path) -> None:
    """An idle account in the state file a track's headroom check falls back to: a track reads a
    usage window whatever the runtime, and nothing here may reach the real endpoint."""
    window = {"utilization": 1, "resets_at": "2099-01-01T00:00:00+00:00"}
    cached = {
        "utilization": {"five_hour": window, "seven_day": window},
        "fetchedAtMs": int(time.time() * 1000) + 3_600_000,
    }
    (home / ".claude.json").write_text(json.dumps({"cachedUsageUtilization": cached}))


@pytest.fixture(scope="module")
def scratch(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Scratch]:
    base = tmp_path_factory.mktemp("planning-in-repo")
    origin, working_copy = working_copy_of(base)
    record = base / "agent.jsonl"
    argv = acp_agent.command(record, act=[])
    commit_files(
        working_copy,
        "plan and build",
        {
            "abk.yaml": abk_yaml(argv),
            "openspec/config.yaml": "schema: spec-driven\n",
            "runs/units.json": UNITS,
            "docs/unit_graph.md": "graph\n",
            SOURCE: "def main() -> None: ...\n",
            ".gitignore": "runs/leases/\nruns/locks/\nruns/unit-logs/\nruns/*.lock\n",
            **change_files(CHANGE),
        },
    )
    git(working_copy, "push", "-q", "origin", "main")
    git(working_copy, "checkout", "-q", "-b", "feature-work")
    (working_copy / SOURCE).write_text("def main() -> None: ...\n" + EDIT)
    home = base / "home"
    home.mkdir()
    write_usage_cache(home)
    # The caches stay the real ones so `npx` and `uv` do not fetch again under the scratch home.
    real = Path.home()
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "npm_config_cache": os.environ.get("npm_config_cache", str(real / ".npm")),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(real / ".cache" / "uv")),
        "ABK_RUNTIME": "acp",
    }
    for name in ("ABK_CONFIG", "ABK_WORKTREE_ROOT", "GH_TOKEN", "ABK_GH_TOKEN"):
        env.pop(name, None)
    setup = InRepo(origin=origin, working_copy=working_copy, worktree=home / "unused")
    yield Scratch(
        base=base,
        setup=setup,
        home=home,
        record=record,
        before=standing(working_copy),
        env=env,
    )


class Installed(Ran):
    """The install's result and what the pipeline worktree held right after it."""

    branch: str
    head: str
    origin_head: str
    units: str


@pytest.fixture(scope="module")
def installed(scratch: Scratch) -> Installed:
    """`abk install-timers --no-enable`, run in the working copy the way a person would."""
    ran = abk(scratch, "install-timers", "--no-enable", cwd=scratch.working_copy)
    assert ran.returncode == 0, ran.output
    worktree = scratch.worktree
    return Installed(
        returncode=ran.returncode,
        output=ran.output,
        branch=git(worktree, "rev-parse", "--abbrev-ref", "HEAD"),
        head=git(worktree, "rev-parse", "HEAD"),
        origin_head=git(scratch.origin, "rev-parse", "main"),
        units=(worktree / "runs" / "units.json").read_text(),
    )


def installation_of(root: Path) -> Installation:
    installation = Installation(config.load(root / "abk.yaml"), root)
    installation.activate()
    return installation


class Landed(Frozen):
    """The verify step over a landed change: the refusal after a source edit, then the pass."""

    refused: Ran
    kept_after_refusal: bool
    passed: Ran
    change_left: bool
    archives: int


@pytest.fixture(scope="module")
def landed(scratch: Scratch, installed: Installed, openspec_cli: None) -> Landed:
    """A unit's work landing on the default branch, verified and archived once: it leaves the
    archived `landed` spec and the unit in the pipeline worktree for the tests that need them."""
    worktree = scratch.worktree
    git(worktree, "fetch", "-q", "origin")
    git(worktree, "merge", "-q", "--ff-only", "origin/main")
    # The unit's branch and pull request, then its work landing on the default branch.
    files = {**change_files("landed", done=True), "src/landed.py": "x = 1\n"}
    commit_files(worktree, "landed", files)
    git(worktree, "branch", "spec/landed/1", "HEAD")
    forge, repo = installation_of(worktree).forge_of("app")
    number = forge.create_pr(repo, head="spec/landed/1", base="main", title="landed", body="")
    git(worktree, "push", "-q", "origin", "HEAD:main")
    store = UnitStore(worktree / "runs" / "units.json")
    store.upsert([stored_unit("landed/1", change="landed", repo="app")])
    store.set_state("landed/1", MERGED, pr=number, branch="spec/landed/1")
    # The store, a state file and the graph page are dirty: all planning paths.
    (worktree / "runs" / "verified.note").write_text("state\n")
    (worktree / "docs" / "unit_graph.md").write_text("graph, regenerated\n")
    (worktree / SOURCE).write_text("def main() -> None: ...\n# edited in the worktree\n")

    refused = in_pipeline(scratch, "verify", "landed")
    kept = (worktree / "openspec/changes/landed").is_dir()

    git(worktree, "checkout", "-q", "--", SOURCE)
    passed = in_pipeline(scratch, "verify", "landed")
    archives = list((worktree / "openspec/changes/archive").glob("*-landed"))
    return Landed(
        refused=refused,
        kept_after_refusal=kept,
        passed=passed,
        change_left=(worktree / "openspec/changes/landed").exists(),
        archives=len(archives),
    )


def test_install_makes_the_pipeline_worktree_and_leaves_the_working_copy_alone(
    scratch: Scratch, installed: Installed
) -> None:
    assert installed.returncode == 0, installed.output
    worktree = scratch.worktree
    assert worktree.is_dir(), installed.output
    common = Path(git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert common.resolve() == (scratch.working_copy / ".git").resolve()
    # Detached at install, at the tip of the default branch, holding the repository's own store.
    assert installed.branch == "HEAD"
    assert installed.head == installed.origin_head
    assert installed.units == UNITS

    marker = scratch.working_copy / ".git" / "abk-pipeline-worktree"
    assert Path(marker.read_text().strip()).resolve() == worktree.resolve()

    units = sorted((scratch.home / ".config" / "systemd" / "user").glob("abk-*.service"))
    assert units, f"no unit was written\n{installed.output}"
    for unit in units:
        assert f"WorkingDirectory={worktree}" in unit.read_text(), unit.name
    assert "nothing is scheduled" in installed.output
    assert_untouched(scratch)


def test_a_tick_in_the_pipeline_worktree_follows_origin_and_stops_on_a_divergence(
    scratch: Scratch, installed: Installed
) -> None:
    assert installed.returncode == 0, installed.output
    tip = publish_elsewhere(
        scratch.setup, change_files("added-elsewhere"), "a change from elsewhere"
    )

    # Which code the tick runs is the interpreter's package, not the worktree's files: a unit's
    # run resolves the worktree's environment, this scratch runs the kit under test.
    code = code_ran(scratch)
    print(f"the tick ran the code at {code}")
    assert code == Path(agent_build_kit.__file__).resolve()
    assert not code.is_relative_to(scratch.worktree)
    assert not code.is_relative_to(scratch.working_copy)

    moved = in_pipeline(scratch, "tick")

    assert f"planning worktree moved to refs/remotes/origin/main ({tip[:10]})" in moved.output
    assert SYNC_STOPPED not in moved.output
    assert git(scratch.worktree, "rev-parse", "HEAD") == tip
    assert (scratch.worktree / "openspec/changes/added-elsewhere/tasks.md").is_file()
    assert_untouched(scratch)

    # A commit made in the worktree, and another on origin: neither holds the other.
    commit_files(scratch.worktree, "made here", {"notes/here.md": "here\n"})
    publish_elsewhere(scratch.setup, {"notes/there.md": "there\n"}, "made there")

    stopped = in_pipeline(scratch, "tick")

    assert stopped.returncode == 1, stopped.output
    lines = [line for line in stopped.output.splitlines() if SYNC_STOPPED in line]
    assert len(lines) == 1, stopped.output
    assert "diverged: 1 commits of its own, 1 new" in lines[0]
    assert_untouched(scratch)
    # Drop only the commit made here, back to the tip: what other tests left uncommitted stays.
    git(scratch.worktree, "fetch", "-q", "origin")
    git(scratch.worktree, "reset", "-q", "--keep", "origin/main")


def test_verify_passes_with_only_planning_paths_dirty_refuses_a_source_edit_and_archives(
    scratch: Scratch, landed: Landed
) -> None:
    refused, passed = landed.refused, landed.passed

    assert refused.returncode == 1, refused.output
    assert SOURCE in refused.output, refused.output
    assert landed.kept_after_refusal

    assert passed.returncode == 0, passed.output
    assert "archived landed" in passed.output
    assert "nothing to deploy" not in passed.output, "the src/ rule did not see src/landed.py"
    assert not landed.change_left
    assert landed.archives == 1, passed.output
    assert_untouched(scratch)


def test_a_planning_commit_holds_only_planning_paths_and_a_track_publishes_both_ways(
    scratch: Scratch, landed: Landed
) -> None:
    worktree = scratch.worktree
    inst = installation_of(worktree)
    (worktree / "openspec/changes" / CHANGE / "proposal.md").write_text(PROPOSAL + "\n- More.\n")
    (worktree / SOURCE).write_text("def main() -> None: ...\n# not for the planning commit\n")
    # The archive wrote the new capability's Purpose as a placeholder, which the check refuses.
    archived = worktree / "openspec/specs/landed/spec.md"
    assert archived.is_file(), landed.passed.output
    archived.write_text(
        "\n".join(
            "The app exposes a marker function that other modules call to read the build marker."
            if line.startswith("TBD")
            else line
            for line in archived.read_text().splitlines()
        )
        + "\n"
    )

    committed = commit_planning(
        inst, stored_unit(f"{CHANGE}/1", change=CHANGE, repo="app"), "planning: reword the proposal"
    )

    files = git(worktree, "show", "--name-only", "--format=", committed.commit).splitlines()
    planning = [p.rstrip("/") for p in inst.planning_paths]
    outside = [f for f in files if not any(f == p or f.startswith(f"{p}/") for p in planning)]
    assert f"openspec/changes/{CHANGE}/proposal.md" in files, files
    assert outside == [], outside
    assert git(worktree, "diff", "--cached", "--name-only") == ""
    assert git(worktree, "diff", "--name-only") == SOURCE
    assert standing(scratch.working_copy).index == scratch.before.index
    assert_untouched(scratch)

    # What a track publishes is the run log the scripted agent writes, not these commits.
    git(worktree, "checkout", "-q", "--", SOURCE)
    git(worktree, "reset", "-q", "--hard", "origin/main")

    direct = track_run(scratch, "direct")
    assert direct.returncode == 0, direct.output
    assert "health phase done" in direct.output, direct.output
    assert git(scratch.origin, "show", "main:runs/acceptance-direct.md") == "# Run log direct"
    assert "track:" in git(scratch.origin, "log", "main", "--format=%s", "-1"), direct.output
    assert planning_branches(scratch) == []

    abk_file = worktree / "abk.yaml"
    abk_file.write_text(abk_file.read_text().replace('"direct"', '"branch"'))
    branch = track_run(scratch, "branch")
    assert branch.returncode == 0, branch.output
    published = planning_branches(scratch)
    assert len(published) == 1, branch.output
    assert git(scratch.origin, "show", f"{published[0]}:runs/acceptance-branch.md") == (
        "# Run log branch"
    )
    pulls = json.loads((worktree / "runs" / "local-prs.json").read_text())
    heads = [pull["head"] for pull_list in pulls.values() for pull in pull_list]
    assert published[0] in heads, pulls
    assert "# Run log branch" not in git(scratch.origin, "log", "main", "-p", "-1")
    assert_untouched(scratch)


def track_run(scratch: Scratch, mode: str) -> Ran:
    """A health phase through the pipeline worktree's config; the scripted agent writes the run
    log `acceptance-<mode>.md` in the state directory."""
    script(
        scratch,
        [
            {
                "edit": str(scratch.worktree / "runs" / f"acceptance-{mode}.md"),
                "content": f"# Run log {mode}",
            }
        ],
    )
    return in_pipeline(scratch, "track", "health", "--project", "app")


def planning_branches(scratch: Scratch) -> list[str]:
    refs = git(scratch.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/planning/")
    return refs.splitlines()


def hook(scratch: Scratch, unit: Path, target: str) -> str:
    """The policy hook's answer to a write of `target` from the unit worktree: empty when it has
    no objection."""
    paths = [
        p for p in installation_of(scratch.worktree).planning_paths if not Path(p).is_absolute()
    ]
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(unit / target)},
        "cwd": str(unit),
    }
    run = subprocess.run(
        [sys.executable, "-m", "agent_build_kit.hooks.policy", "--planning-paths", ",".join(paths)],
        input=json.dumps(payload),
        env=scratch.env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return run.stdout.strip()


def test_a_unit_worktree_is_fenced_and_abk_run_there_finds_the_live_installation(
    scratch: Scratch, installed: Installed
) -> None:
    assert installed.returncode == 0, installed.output
    # Something only the live store holds, so the unit worktree's own copy reads differently.
    UnitStore(scratch.worktree / "runs" / "units.json").upsert(
        [stored_unit("fence/1", change="fence", repo="app")]
    )
    unit = scratch.base / "unit"
    git(
        scratch.working_copy,
        "worktree",
        "add",
        "-q",
        "-b",
        "spec/feature/1",
        str(unit),
        "origin/main",
    )

    for target in ("openspec/changes/feature/tasks.md", "runs/units.json", "abk.yaml"):
        assert "BLOCKED:" in hook(scratch, unit, target), target
    assert hook(scratch, unit, "src/x.py") == ""

    here = abk(scratch, "status", cwd=unit)
    live = in_pipeline(scratch, "status")
    own = abk(scratch, "status", cwd=unit, config_file=unit / "abk.yaml")
    assert here.returncode == 0, here.output
    assert untimed(here) == untimed(live), (
        "abk by hand in a unit worktree did not find the live one"
    )
    assert untimed(here) != untimed(own)

    named = abk(scratch, "status", cwd=scratch.working_copy)
    assert str(scratch.worktree) in named.output, named.output
    assert f"--config {scratch.worktree / 'abk.yaml'}" in named.output
    refused = abk(scratch, "tick", cwd=scratch.working_copy)
    assert refused.returncode == 2, refused.output
    assert str(scratch.worktree) in refused.output
    assert_untouched(scratch)
