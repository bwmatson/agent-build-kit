"""Binding the runner's steps to real git, Claude and gh.

`UnitRunner` is pure sequencing; these are the callables it sequences. They
are the last place where a mistake reaches a real repository, so the tests
here are about the *shape of the commands* — which flags are passed, and what
is deliberately absent.

Three things carry real weight:

- **Every Claude run carries the policy hook and a budget.** A run without
  them is an unattended agent with no deny list and no spend limit.
- **The push uses the SHA we last recorded**, not a bare lease.
- **A PR is created once and updated thereafter**, since a unit's branch is
  pushed again on every restack.
"""

import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_build_kit.config import ProjectConfig, models
from agent_build_kit.pipeline.pr_replies import MARKER
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, RUNNING, SATISFIED
from agent_build_kit.pipeline.wiring import (
    Tier2Session,
    branch_commits,
    build_base_moved,
    build_close_pr,
    build_commit,
    build_open_pr,
    build_push,
    build_run_claude,
    build_run_review,
    build_tier1,
    build_upstream_incomplete,
    is_linear,
    tip,
)
from tests.conftest import make_installation
from tests.factories import git, init_repo, unit
from tests.forges.stand_in import StandInForge, lookup


class Recorder:
    def __init__(self, *, stdout: str = "", returncode: int = 0) -> None:
        self.commands: list[list[str]] = []
        self.stdout = stdout
        self.returncode = returncode

    def __call__(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(args)
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "")


def test_a_claude_run_carries_the_policy_hook(tmp_path: Path) -> None:
    """Without it the unattended agent has no deny list: it could merge its
    own PR or force-push over someone's commit."""
    recorder = Recorder()

    build_run_claude(run=recorder)("do the thing", cwd=tmp_path)

    command = " ".join(recorder.commands[0])
    assert "--settings" in command
    assert "agent_build_kit.hooks.policy" in command


def test_a_claude_run_streams_and_answers_with_the_result_text(tmp_path: Path) -> None:
    """Streamed so the tick log can show progress; the caller still gets the
    plain answer, which the review step parses as JSON."""
    recorder = Recorder()
    recorder.stdout = '{"type": "result", "result": "{\\"approved\\": true}"}\n'

    answer = build_run_claude(run=recorder)("do the thing", cwd=tmp_path)

    assert "stream-json" in recorder.commands[0]
    assert answer == '{"approved": true}'


def test_a_claude_run_carries_no_dollar_budget(tmp_path: Path) -> None:
    """The session window is the real limit and `usage_guard` reads it live
    from Anthropic. A dollar figure beside it is a second, notional ceiling
    that has to be guessed, drifts from what a unit actually costs, and — as
    the pilot pre-flight showed — silently refuses to start a run at all when
    guessed too low."""
    recorder = Recorder()

    build_run_claude(run=recorder)("do the thing", cwd=tmp_path)

    assert "--max-budget-usd" not in recorder.commands[0]


def test_a_claude_run_cannot_merge_even_if_the_hook_fails(tmp_path: Path) -> None:
    """Belt and braces: the deny list is also passed as a tool restriction, so
    a broken hook isn't the only thing standing between the agent and a merge."""
    recorder = Recorder()

    build_run_claude(run=recorder)("do the thing", cwd=tmp_path)

    command = " ".join(recorder.commands[0])
    assert "gh pr merge" in command
    assert "--disallowedTools" in command


def test_committing_reports_whether_anything_was_committed(tmp_path: Path) -> None:
    """The runner uses this to decide whether to review: an empty commit means
    the implementation run produced nothing."""
    init_repo(tmp_path)
    commit = build_commit()

    assert commit("test: nothing yet", cwd=tmp_path) == 0

    (tmp_path / "file.txt").write_text("x")
    assert commit("test: something", cwd=tmp_path) == 1


def test_a_commit_message_says_which_unit_it_belongs_to(tmp_path: Path) -> None:
    """A branch's history should be readable without the planning repo open."""
    init_repo(tmp_path)
    (tmp_path / "file.txt").write_text("x")

    build_commit(unit_id="add-marker/1")("test: covers it", cwd=tmp_path)

    body = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    assert "add-marker/1" in body


def test_tier_one_runs_lint_types_and_tests(tmp_path: Path) -> None:
    """All three, because the branch tip has to be green on all three before a
    reviewer is asked to look."""
    recorder = Recorder()
    repo = tmp_path / "plain"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")

    build_tier1(run=recorder, changed=lambda *a: ["tests/test_x.py"])(cwd=repo, base="main")

    commands = " ".join(" ".join(c) for c in recorder.commands)
    assert "pre-commit" in commands
    assert "pytest" in commands


def test_tier_one_fails_if_any_step_fails(tmp_path: Path) -> None:
    recorder = Recorder(returncode=1)

    passed, _ = build_tier1(run=recorder, changed=lambda *a: [])(cwd=tmp_path, base="main")
    assert passed is False


def test_the_push_uses_the_sha_we_last_recorded(tmp_path: Path) -> None:
    """A bare lease would compare against a ref a fetch may have just moved."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    pushed: list[tuple] = []

    build_push(
        store, push=lambda repo, branch, last_pushed: pushed.append((branch, last_pushed)) or "sha1"
    )("spec/add-marker/1", cwd=tmp_path)

    assert pushed[0] == ("spec/add-marker/1", None), "first push has nothing to protect"


def test_a_branch_the_host_moved_is_adopted_not_pushed(tmp_path: Path) -> None:
    """Every push passes here, so this catches a unit the host moved whoever
    it is — after a stack merge the host rewrites every PR above the merged
    one, not only its direct child. Pushing would fail its lease forever; the
    host's head is taken instead, and review sees it before anything is sent."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    store.record_push("add-marker/1", "before-the-merge")
    store.record_approval("add-marker/1", "before-the-merge")
    pushed: list[str] = []
    adopted: list[dict] = []

    push = build_push(
        store,
        push=lambda repo, branch, last_pushed: pushed.append(branch) or "sha1",
        remote_head_of=lambda repo, branch: "host-rebased",
        adopt=lambda repo, branch, **k: adopted.append(k) or "host-rebased",
    )
    with pytest.raises(HostMoved):
        push("spec/add-marker/1", cwd=tmp_path)

    assert pushed == []
    assert adopted == [
        {"host_head": "host-rebased", "last_pushed": "before-the-merge", "cwd": tmp_path}
    ]
    assert store.get("add-marker/1").pushed == "host-rebased", "the next lease holds"
    assert store.get("add-marker/1").approved == ""


def test_a_push_whose_recording_was_lost_is_not_taken_for_a_host_move(tmp_path: Path) -> None:
    """A crash between a push and recording it: the host is ahead of the store
    but level with the local branch. Nobody moved it, so nothing is adopted
    and the approval stands."""
    repo = init_repo(tmp_path / "repo")
    (repo / "x.txt").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "x")
    git(repo, "branch", "-q", "spec/add-marker/1")
    head = git(repo, "rev-parse", "HEAD").strip()
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    store.record_push("add-marker/1", "before")
    store.record_approval("add-marker/1", head)
    pushed: list[tuple] = []

    build_push(
        store,
        push=lambda repo, branch, last_pushed: pushed.append((branch, last_pushed)) or head,
        remote_head_of=lambda repo, branch: head,
        adopt=lambda *a, **k: pytest.fail("nothing to adopt"),
    )("spec/add-marker/1", cwd=repo)

    assert pushed == [("spec/add-marker/1", head)], "the lease names what the host has"
    assert store.get("add-marker/1").approved == head


def test_is_linear_raises_no_alarm_over_a_base_it_cannot_resolve(tmp_path: Path) -> None:
    """Only a definite "not an ancestor" is not linear; an unknown ref is unknown."""
    repo = init_repo(tmp_path / "repo")
    (repo / "x.txt").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "x")

    assert is_linear(repo, "no-such-branch") is True


def test_is_linear_follows_whether_the_base_tip_is_in_the_branch(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "x.txt").write_text("x")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "x")
    git(repo, "checkout", "-qb", "child")
    (repo / "y.txt").write_text("y")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "y")

    assert is_linear(repo, "main") is True

    git(repo, "checkout", "-q", "main")
    (repo / "z.txt").write_text("z")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "z")
    git(repo, "checkout", "-q", "child")

    assert is_linear(repo, "main") is False


def test_a_branch_the_host_still_has_as_pushed_is_pushed(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    store.record_push("add-marker/1", "sha0")
    pushed: list[tuple] = []

    build_push(
        store,
        push=lambda repo, branch, last_pushed: pushed.append((branch, last_pushed)) or "sha1",
        remote_head_of=lambda repo, branch: "sha0",
    )("spec/add-marker/1", cwd=tmp_path)

    assert pushed == [("spec/add-marker/1", "sha0")]


def test_a_pr_is_created_once_and_updated_after_that(tmp_path: Path) -> None:
    """Every restack pushes the branch again; a second create would fail, and
    worse, a third would look like the unit was stuck."""
    first_time = StandInForge(existing=None)
    already_open = StandInForge(existing=7)

    first = build_open_pr(for_repo=lookup(first_time))(unit(), body="b", base="main", cwd=tmp_path)
    again = build_open_pr(for_repo=lookup(already_open))(
        unit(), body="b", base="main", cwd=tmp_path
    )

    assert first == again == 7
    assert len(first_time.created) == 1 and not first_time.updated
    assert not already_open.created and already_open.updated == [
        {"pr": 7, "base": "main", "body": "b"}
    ]


def test_the_pr_targets_the_units_base_branch(tmp_path: Path) -> None:
    """A stacked unit's PR must show only its own diff, which means basing it
    on its parent rather than on main."""
    forge = StandInForge(existing=None)

    build_open_pr(for_repo=lookup(forge))(unit(), body="b", base="spec/add-marker/0", cwd=tmp_path)

    assert forge.created[0]["base"] == "spec/add-marker/0"


def test_closing_posts_the_reason_before_closing(tmp_path: Path) -> None:
    """The explanation must never be missing, so it is posted before the
    close is even attempted.

    Checked against one ordered call log, not two separate lists: those would
    still pass even if the close came first.
    """
    forge = StandInForge(existing=7)

    build_close_pr(for_repo=lookup(forge))(unit(), 7, "implemented elsewhere")

    assert forge.calls == [("comment", 7), ("close", 7)]
    assert forge.comments == ["implemented elsewhere\n" + MARKER]


def test_the_posted_reason_is_marked_as_the_pipelines_own(tmp_path: Path) -> None:
    """Unmarked, the reason would read back as a reviewer's new comment on the
    next poll and send a satisfied unit to rework over its own explanation —
    see `events.review_lines` and `_latest_comment`."""
    forge = StandInForge(existing=7)

    build_close_pr(for_repo=lookup(forge))(unit(), 7, "implemented elsewhere")

    assert MARKER in forge.comments[0]


def test_a_failed_reason_post_leaves_the_pull_request_open(tmp_path: Path) -> None:
    """A post that fails must not be followed by a close: that would leave
    the PR shut with no reason ever posted on it."""
    forge = StandInForge(existing=7, comment_error=True)

    with pytest.raises(RuntimeError, match="not posted"):
        build_close_pr(for_repo=lookup(forge))(unit(), 7, "implemented elsewhere")

    assert forge.closed == []


def test_a_rejected_commit_is_not_reported_as_nothing_to_commit(tmp_path: Path) -> None:
    """A failing pre-commit hook and an empty diff both used to return 0, so
    the runner blamed the model for producing nothing. On an unattended run
    that misdiagnosis is the whole trail anyone has."""
    init_repo(tmp_path)
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'hook exploded' >&2\nexit 1\n")
    hook.chmod(0o755)
    (tmp_path / "file.txt").write_text("x")

    with pytest.raises(RuntimeError, match="hook exploded"):
        build_commit()("test: covers it", cwd=tmp_path)


def test_a_claude_run_can_read_the_planning_repo(tmp_path: Path) -> None:
    """The unit is built in the target repo's worktree, but the spec it is
    built from lives in the planning repo. Without this the agent cannot see
    the change at all — which is how the first pilot run produced nothing."""
    recorder = Recorder()

    build_run_claude(run=recorder, planning_repo=tmp_path / "meta")("do it", cwd=tmp_path)

    command = recorder.commands[0]
    assert "--add-dir" in command
    assert str(tmp_path / "meta" / "openspec") in command


def workspace(tmp_path: Path, members: list[str], *, with_tests: list[str]) -> Path:
    """A uv workspace shaped like app and platform: members with their
    own tests/, and no root-level test suite."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[tool.uv.workspace]\nmembers = [" + ", ".join(f'"{m}"' for m in members) + "]\n"
    )
    for member in members:
        (repo / member).mkdir()
        if member in with_tests:
            (repo / member / "tests").mkdir()
    return repo


def test_lint_is_scoped_to_what_the_unit_changed(tmp_path: Path) -> None:
    """`--all-files` fails a unit for problems in files it never touched: a
    pre-existing type error in another member would fail a unit whose own
    files are clean."""
    recorder = Recorder()
    repo = workspace(tmp_path, ["shared"], with_tests=["shared"])

    build_tier1(run=recorder, changed=lambda *a: ["shared/tests/test_x.py"])(cwd=repo, base="main")

    lint = " ".join(recorder.commands[0])
    assert "--all-files" not in lint
    assert "--from-ref main --to-ref HEAD" in lint


def test_tests_run_per_workspace_member_the_unit_touched(tmp_path: Path) -> None:
    """Every member has a top-level `src`, so with all of them in one
    environment one member's tests import another member's `src`.
    `--package --isolated` is what CI's one-member checkout gives for free."""
    calls: list[tuple] = []
    repo = workspace(tmp_path, ["shared", "svc-a", "svc-b"], with_tests=["shared", "svc-b"])

    def run(command, **kwargs):
        calls.append((command, kwargs.get("cwd")))
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(run=run, changed=lambda *a: ["shared/tests/test_x.py"])(cwd=repo, base="main")

    tested = [c for c, _ in calls if "pytest" in c]
    assert tested == [["uv", "run", "--package", "shared", "--isolated", "pytest", "shared", "-q"]]


def test_a_root_change_tests_every_member(tmp_path: Path) -> None:
    """Registering a marker in the root pyproject.toml affects every member,
    so touching nothing under one of them cannot mean testing none of them."""
    calls: list[tuple] = []
    repo = workspace(tmp_path, ["shared", "svc-a", "svc-b"], with_tests=["shared", "svc-b"])

    def run(command, **kwargs):
        calls.append((command, kwargs.get("cwd")))
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(run=run, changed=lambda *a: ["pyproject.toml"])(cwd=repo, base="main")

    tested = sorted(c[c.index("--package") + 1] for c, _ in calls if "pytest" in c)
    assert tested == ["shared", "svc-b"]
    assert "svc-a" not in tested, "no tests/ dir, nothing to run"


def test_a_plain_repo_still_runs_pytest_at_the_root(tmp_path: Path) -> None:
    """Not every repo is a workspace; one without members is tested in place."""
    calls: list[tuple] = []
    repo = tmp_path / "plain"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n")

    def run(command, **kwargs):
        calls.append((command, kwargs.get("cwd")))
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(run=run, changed=lambda *a: ["tests/test_x.py"])(cwd=repo, base="main")

    assert [c for c, _ in calls if "pytest" in c] == [["uv", "run", "pytest", "-q"]]


def test_whole_repo_mode_lints_and_tests_everything_regardless_of_the_diff(
    tmp_path: Path,
) -> None:
    """A unit that produced no commits of its own has no diff to scope tier 1
    to: `changed` returning `[]` would otherwise lint an empty range and test
    no member at all, which is an empty-scope pass rather than proof anything
    actually works. `whole_repo=True` has to run a real lint and one test
    command per testable member instead, whatever `changed` says."""
    calls: list[tuple] = []
    repo = workspace(tmp_path, ["shared", "svc-a", "svc-b"], with_tests=["shared", "svc-b"])

    def run(command, **kwargs):
        calls.append((command, kwargs.get("cwd")))
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(run=run, changed=lambda *a: [])(cwd=repo, base="main", whole_repo=True)

    lint = [c for c, _ in calls if "pre-commit" in c][0]
    assert "--all-files" in lint
    assert "--from-ref" not in lint

    tested = sorted(c[c.index("--package") + 1] for c, _ in calls if "pytest" in c)
    assert tested == ["shared", "svc-b"]


def test_whole_repo_mode_still_fails_on_a_failing_member(tmp_path: Path) -> None:
    """The lint passes — only `shared`'s tests fail — so whole-repo mode has
    to be judged the same way `test_commands` is: any one member failing
    fails the unit, not just a failing lint."""
    repo = workspace(tmp_path, ["shared"], with_tests=["shared"])

    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1 if "pytest" in command else 0, "", "")

    passed, _ = build_tier1(run=run, changed=lambda *a: [])(cwd=repo, base="main", whole_repo=True)

    assert passed is False


def test_a_failing_member_fails_the_unit(tmp_path: Path) -> None:
    repo = workspace(tmp_path, ["shared"], with_tests=["shared"])
    failing = Recorder(returncode=1)

    passed, _ = build_tier1(run=failing, changed=lambda *a: ["shared/x.py"])(cwd=repo, base="main")
    assert passed is False


def test_a_root_documentation_change_does_not_fan_out(tmp_path: Path) -> None:
    """A unit touching CLAUDE.md would fan out to an isolated install per
    member. Markdown is the one root change that cannot affect a test run;
    everything else outside the members still fans out."""
    calls: list[tuple] = []
    repo = workspace(tmp_path, ["svc-a", "shared"], with_tests=["svc-a", "shared"])

    def run(command, **kwargs):
        calls.append((command, kwargs.get("cwd")))
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(run=run, changed=lambda *a: ["CLAUDE.md", "svc-a/tests/test_x.py"])(
        cwd=repo, base="main"
    )

    tested = [c[c.index("--package") + 1] for c, _ in calls if "pytest" in c]
    assert tested == ["svc-a"], "only the member the unit actually touched"


def test_tier_one_reports_what_failed_not_just_that_it_did(tmp_path: Path) -> None:
    """The output is what a retry needs; without it the unit is rebuilt blind."""
    repo = workspace(tmp_path, ["shared"], with_tests=["shared"])
    failing = Recorder(returncode=1, stdout="E   ImportError: cannot import name 'geo'")

    passed, output = build_tier1(run=failing, changed=lambda *a: ["shared/x.py"])(
        cwd=repo, base="main"
    )

    assert passed is False
    assert "ImportError" in output


def test_a_claude_run_sees_the_specs_not_the_whole_planning_repo(tmp_path: Path) -> None:
    """Units run in worktrees under the planning repo's runs/ directory, so
    `--add-dir <planning repo>` handed every agent every other unit's working
    tree. In the pilot, unit 2's agent reached into unit 1's worktree and
    committed there, inventing a unit id for the trailer. Only openspec/ is
    the agent's business."""
    recorder = Recorder()
    planning = tmp_path / "meta"

    build_run_claude(run=recorder, planning_repo=planning)("do it", cwd=tmp_path)

    exposed = recorder.commands[0][recorder.commands[0].index("--add-dir") + 1]
    assert exposed == str(planning / "openspec")
    assert str(planning) not in [c for c in recorder.commands[0] if c == str(planning)]


def test_worktrees_live_outside_the_planning_repo(tmp_path: Path) -> None:
    """Nesting them under the planning repo caused two distinct failures. An
    agent could reach every other unit's tree through --add-dir, and pyrefly
    resolved a target repo's imports against the planning repo's own src/ and
    config from an ancestor directory — reporting type errors in a member
    that do not exist when the same commit is checked out anywhere else."""
    from agent_build_kit.config import ConfigError, WorkspaceConfig
    from agent_build_kit.installation import Installation

    planning = tmp_path / "planning"
    planning.mkdir()
    by_default = Installation(WorkspaceConfig(), planning)
    assert by_default.worktree_root.is_absolute()
    assert planning not in by_default.worktree_root.parents

    inside = WorkspaceConfig.model_validate({"planning": {"worktree_root": str(planning / "runs")}})
    with pytest.raises(ConfigError, match="outside the planning repo"):
        Installation(inside, planning)


def test_a_member_is_named_by_its_package_not_its_directory(tmp_path: Path) -> None:
    """`uv run --package` takes the package name. A `shared/` directory that
    declares `app-shared` fails tier 1 with "The workspace does not have a
    member shared"; a workspace whose members with tests happen to have
    matching names only works by luck."""
    calls: list[list[str]] = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["shared"]\n')
    (repo / "shared").mkdir()
    (repo / "shared" / "tests").mkdir()
    (repo / "shared" / "pyproject.toml").write_text('[project]\nname = "app-shared"\n')

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(run=run, changed=lambda *a: ["shared/x.py"])(cwd=repo, base="main")

    tested = next(c for c in calls if "pytest" in c)
    assert tested[tested.index("--package") + 1] == "app-shared", "the package"
    assert tested[-2] == "shared", "but the directory is still what pytest collects"


def test_a_member_with_no_declared_name_falls_back_to_its_directory(tmp_path: Path) -> None:
    """An unparseable or nameless member should not take tier 1 down with it."""
    calls: list[list[str]] = []
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["odd"]\n')
    (repo / "odd").mkdir()
    (repo / "odd" / "tests").mkdir()

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(run=run, changed=lambda *a: ["odd/x.py"])(cwd=repo, base="main")

    tested = next(c for c in calls if "pytest" in c)
    assert tested[tested.index("--package") + 1] == "odd"


def test_the_models_are_named_by_alias_not_by_version(tmp_path: Path) -> None:
    """`claude --model` resolves a bare alias to the latest of that family, so
    an alias tracks new releases on its own. A pinned id would quietly go stale
    and need someone to notice."""

    for name in (models().implement, models().review):
        assert "-" not in name, f"{name} looks like a pinned id, not an alias"


def test_build_and_rework_run_on_the_same_model() -> None:
    """Both are writing code against a spec; the rework just has a reviewer's
    words as part of its input. Splitting them would mean a unit's branch was
    written by two different models, for no reason anyone could name."""

    assert models().rework == models().implement


def test_the_build_runs_on_opus(tmp_path: Path) -> None:
    recorder = Recorder()

    build_run_claude(run=recorder)("do it", cwd=tmp_path)

    command = recorder.commands[0]
    assert command[command.index("--model") + 1] == "opus"


def test_a_rework_is_evaluated_by_a_different_model_than_reworked_it() -> None:
    """Where independence is held, it is held here: a rework is a small
    targeted edit, and the model that made it is the worst judge of whether it
    landed. A fresh build is deliberately not covered by this — see settings."""

    assert models().rework_review != models().rework


def test_the_standard_review_runs_on_opus(tmp_path: Path) -> None:
    recorder = Recorder()

    build_run_review(run=recorder)(cwd=tmp_path)

    command = recorder.commands[0]
    assert command[command.index("--model") + 1] == "opus"


def test_a_rework_s_review_runs_on_fable(tmp_path: Path) -> None:

    recorder = Recorder()

    build_run_review(run=recorder, model=models().rework_review)(cwd=tmp_path)

    command = recorder.commands[0]
    assert command[command.index("--model") + 1] == "fable"


def test_after_a_squash_merge_only_the_unit_s_own_commits_are_replayed(tmp_path: Path) -> None:
    """c/2 is squash-merged after c/3 forked from an earlier commit of it.
    Replaying from where c/3 and main last met re-applies all of c/2's
    original commits over its squashed form; the replay must start where c/3
    left its parent's branch."""
    from agent_build_kit.pipeline.unit_store import UnitStore
    from agent_build_kit.pipeline.wiring import own_work_starts_after
    from tests.factories import git, init_repo, stored_unit

    repo = init_repo(tmp_path / "r")

    def commit(name: str, text: str) -> str:
        (repo / name).write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", name)
        return git(repo, "rev-parse", "HEAD")

    commit("base.txt", "base\n")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    fork = commit("mcp.py", "tools = ['a']\n")
    git(repo, "checkout", "-q", "-b", "spec/c/3")
    commit("acting.py", "click\n")
    git(repo, "checkout", "-q", "spec/c/2")
    commit("mcp.py", "tools = ['a', 'b']\n")  # the parent's later review round
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "spec/c/2")
    git(repo, "commit", "-qm", "c/2 (#2)")
    git(repo, "checkout", "-q", "spec/c/3")

    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("c/2", branch="spec/c/2"), stored_unit("c/3", depends_on=("c/2",))])
    store.set_state("c/2", "merged", branch="spec/c/2")

    start = own_work_starts_after(repo, "main", store.get("c/3"), store)

    assert start == fork
    git(repo, "rebase", "-q", "--onto", "main", start, "spec/c/3")  # applies cleanly
    assert (repo / "mcp.py").read_text() == "tools = ['a', 'b']\n"
    assert (repo / "acting.py").read_text() == "click\n"


def test_own_work_starts_after_looks_through_a_satisfied_unit_with_no_refs(
    tmp_path: Path,
) -> None:
    """c/3 forked straight off c/1's branch — c/2, satisfied on it, never had
    a branch, push or approval of its own. Reading only the direct parent's
    refs finds nothing there and falls back to the plain merge-base, which
    misses the fork and would let c/1's later rework be replayed onto c/3 a
    second time after a squash-merge."""
    from agent_build_kit.pipeline.wiring import own_work_starts_after
    from tests.factories import git, init_repo, stored_unit

    repo = init_repo(tmp_path / "r")

    def commit(name: str) -> str:
        (repo / name).write_text(name)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", name)
        return git(repo, "rev-parse", "HEAD")

    commit("base.txt")
    plain_merge_base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "spec/add-marker/1")
    fork = commit("c1.txt")
    git(repo, "checkout", "-q", "-b", "spec/add-marker/3")
    commit("c3.txt")
    git(repo, "checkout", "-q", "spec/add-marker/1")
    commit("c1-round-2.txt")
    git(repo, "checkout", "-q", "spec/add-marker/3")

    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("add-marker/1"),
            stored_unit("add-marker/2", depends_on=("add-marker/1",)),
            stored_unit("add-marker/3", depends_on=("add-marker/2",)),
        ]
    )
    store.set_state("add-marker/1", IN_REVIEW, branch="spec/add-marker/1")
    store.record_push("add-marker/1", git(repo, "rev-parse", "spec/add-marker/1"))
    store.set_state("add-marker/2", SATISFIED)

    start = own_work_starts_after(repo, "main", store.get("add-marker/3"), store)

    assert start == fork
    assert start != plain_merge_base


def test_predecessor_looks_through_a_satisfied_unit_once_its_parent_merges(
    tmp_path: Path,
) -> None:
    """add-marker/2 is satisfied on add-marker/1's branch. Once add-marker/1
    merges and the base becomes `main`, the predecessor is add-marker/1 —
    which has commits and a PR — not add-marker/2, which never had either."""
    from agent_build_kit.pipeline.wiring import predecessor
    from tests.factories import stored_unit

    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("add-marker/1"),
            stored_unit("add-marker/2", depends_on=("add-marker/1",)),
            stored_unit("add-marker/3", depends_on=("add-marker/2",)),
        ]
    )
    store.set_state("add-marker/2", SATISFIED)
    store.set_state("add-marker/1", MERGED)

    found = predecessor(store.get("add-marker/3"), "main", store)

    assert found is not None
    assert found.id == "add-marker/1"


def test_the_adapt_step_is_told_the_tests_the_previous_work_added(tmp_path: Path) -> None:
    from agent_build_kit.pipeline.wiring import defined_tests_in_range, reset_to, tests_in
    from tests.factories import git, init_repo

    repo = init_repo(tmp_path / "r")
    (repo / "test_old.py").write_text("def test_existing():\n    pass\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "test_old.py").write_text(
        "def test_existing():\n    pass\n\n\nasync def test_new_one():\n    pass\n"
    )
    git(repo, "commit", "-qam", "unit")
    head = git(repo, "rev-parse", "HEAD")

    assert defined_tests_in_range(repo, base, head) == ["test_new_one"]
    assert tests_in(repo) == {"test_existing", "test_new_one"}

    reset_to(repo, base, "refs/spec-driven/pre-adapt/c-3")

    assert git(repo, "rev-parse", "HEAD") == base
    assert git(repo, "rev-parse", "refs/spec-driven/pre-adapt/c-3") == head, "old work kept"


def test_a_test_weakened_in_place_is_told_apart_from_one_left_alone(tmp_path: Path) -> None:
    """A test kept under its old name but quietly weakened — an assertion
    relaxed, a case deleted — must not read as untouched just because its
    name still matches. Comparing bodies, not names, is what catches it."""
    from agent_build_kit.pipeline.wiring import tests_changed
    from tests.factories import git, init_repo

    repo = init_repo(tmp_path / "r")
    (repo / "test_mod.py").write_text(
        "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 1 == 1\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    keep = "refs/spec-driven/pre-adapt/c-3"
    git(repo, "update-ref", keep, "HEAD")

    (repo / "test_mod.py").write_text(
        "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 1 == 2\n"
    )

    assert tests_changed(repo, keep) == {"test_b"}


def _changed_after(
    tmp_path: Path,
    before: str | Mapping[str, str],
    after: str | Mapping[str, str | None],
) -> set[str]:
    """`tests_changed` on a real repo: `before` is committed, `after` written
    over it (a `None` value deletes the file)."""
    from agent_build_kit.pipeline.wiring import tests_changed
    from tests.factories import git, init_repo

    repo = init_repo(tmp_path / "r")
    for name, text in ({"test_mod.py": before} if isinstance(before, str) else before).items():
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    keep = "refs/spec-driven/pre-adapt/c-3"
    git(repo, "update-ref", keep, "HEAD")
    for name, text in ({"test_mod.py": after} if isinstance(after, str) else after).items():
        if text is None:
            (repo / name).unlink()
        else:
            (repo / name).write_text(text)
    return tests_changed(repo, keep)


_DEFAULTS = "def test_defaults():\n    assert 1 == 1\n"


def test_a_test_weakened_in_a_file_whose_path_git_quotes_reads_as_changed(
    tmp_path: Path,
) -> None:
    before = {"test_é.py": "def test_a():\n    assert 1 == 1\n"}
    after = {"test_é.py": "def test_a():\n    pass\n"}

    assert _changed_after(tmp_path, before, after) == {"test_a"}


def test_a_file_that_is_not_utf8_is_compared_without_raising(tmp_path: Path) -> None:
    from agent_build_kit.pipeline.wiring import tests_changed
    from tests.factories import git, init_repo

    repo = init_repo(tmp_path / "r")
    head = b"# caf\xe9\n"
    (repo / "test_mod.py").write_bytes(head + b"def test_a():\n    assert 1 == 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "update-ref", "refs/keep", "HEAD")
    (repo / "test_mod.py").write_bytes(head + b"def test_a():\n    pass\n")

    assert tests_changed(repo, "refs/keep") == {"test_a"}


def test_a_ref_that_does_not_exist_raises_rather_than_reading_as_unchanged(
    tmp_path: Path,
) -> None:
    from agent_build_kit.pipeline.wiring import tests_changed
    from tests.factories import init_repo

    repo = init_repo(tmp_path / "r")

    with pytest.raises(subprocess.CalledProcessError):
        tests_changed(repo, "refs/does-not-exist")


def test_a_test_removed_from_one_file_reads_as_changed_though_another_has_the_name(
    tmp_path: Path,
) -> None:
    both = {"test_a.py": _DEFAULTS, "test_b.py": _DEFAULTS}

    assert _changed_after(tmp_path, both, {"test_a.py": "x = 1\n"}) == {"test_defaults"}


def test_a_test_file_deleted_reads_as_its_tests_changed(tmp_path: Path) -> None:
    both = {"test_a.py": _DEFAULTS, "test_b.py": _DEFAULTS}

    assert _changed_after(tmp_path, both, {"test_a.py": None}) == {"test_defaults"}


def test_a_removed_test_reads_as_changed_though_its_text_survives_in_a_string(
    tmp_path: Path,
) -> None:
    before = {"test_a.py": _DEFAULTS, "test_b.py": "x = 1\n"}
    after = {"test_a.py": "x = 1\n", "test_b.py": 'SRC = "def test_defaults(): pass"\n'}

    assert _changed_after(tmp_path, before, after) == {"test_defaults"}


def test_a_file_rewritten_to_a_syntax_error_reports_its_old_tests(tmp_path: Path) -> None:
    assert _changed_after(tmp_path, _DEFAULTS, "def test_defaults(:\n") == {"test_defaults"}


def test_a_skip_added_over_an_unchanged_body_reads_as_changed(tmp_path: Path) -> None:
    before = "def test_a():\n    assert 1 == 1\n"
    after = "import pytest\n\n\n@pytest.mark.skip\ndef test_a():\n    assert 1 == 1\n"

    assert _changed_after(tmp_path, before, after) == {"test_a"}


def test_a_parametrize_list_shortened_over_an_unchanged_body_reads_as_changed(
    tmp_path: Path,
) -> None:
    body = "def test_a(x):\n    assert x\n"
    before = "import pytest\n\n\n@pytest.mark.parametrize('x', [1, 2, 3])\n" + body
    after = "import pytest\n\n\n@pytest.mark.parametrize('x', [1])\n" + body

    assert _changed_after(tmp_path, before, after) == {"test_a"}


def test_one_of_two_same_named_tests_weakened_reads_as_changed(tmp_path: Path) -> None:
    def source(first: str) -> str:
        return (
            f"class TestA:\n    def test_x(self):\n        {first}\n\n\n"
            "class TestB:\n    def test_x(self):\n        assert 1 == 1\n"
        )

    assert _changed_after(tmp_path, source("assert 1 == 1"), source("pass")) == {"test_x"}


def test_a_review_can_be_told_what_happened_to_the_branch(tmp_path: Path) -> None:
    """The runner passes the reviewer a note when the branch was moved onto a
    changed predecessor. The real review function has to take it: fakes that
    do hide that it does not, and the review crashes."""
    recorder = Recorder()

    build_run_review(run=recorder)(cwd=tmp_path, context="MOVED ONTO A CHANGED PREDECESSOR")

    prompt = recorder.commands[0][recorder.commands[0].index("-p") + 1]
    assert prompt.startswith("MOVED ONTO A CHANGED PREDECESSOR")
    assert "Reply with JSON" in prompt


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n')
    for member, name in (("svc-a", "svc-a"), ("svc-b", "example-svc-b")):
        (tmp_path / member / "tests").mkdir(parents=True)
        (tmp_path / member / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
    return tmp_path


def test_tier_two_runs_each_member_on_its_own_as_tier_one_does(tmp_path: Path) -> None:
    """A rooted run puts every member's `src` in one environment, so
    collection fails before a test runs."""
    from agent_build_kit.profiles.python_uv import PROFILE

    commands = PROFILE.tier2_commands(_workspace(tmp_path), marker="local_stack")

    assert commands == [
        [
            "uv",
            "run",
            "--package",
            "svc-a",
            "--isolated",
            "pytest",
            "svc-a",
            "-m",
            "local_stack",
            "-v",
        ],
        [
            "uv",
            "run",
            "--package",
            "example-svc-b",
            "--isolated",
            "pytest",
            "svc-b",
            "-m",
            "local_stack",
            "-v",
        ],
    ]


def test_a_member_with_no_live_stack_tests_does_not_fail_tier_two(tmp_path: Path) -> None:
    """pytest exits 5 when every test is deselected — most members, for
    `-m local_stack`. That is nothing to run, not a failure."""
    outcomes = iter(
        [
            subprocess.CompletedProcess([], 0, "3 passed in 4.00s", ""),
            subprocess.CompletedProcess([], 5, "12 deselected in 0.10s", ""),
        ]
    )
    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=lambda command, **k: next(outcomes),
        sha=lambda cwd: "abc1234",
    )

    ok, snapshot = session.run(cwd=_workspace(tmp_path))

    assert ok
    assert "3 passed" in snapshot


def test_a_failing_member_fails_tier_two_and_says_why(tmp_path: Path) -> None:
    outcomes = iter(
        [
            subprocess.CompletedProcess([], 1, "", "ERROR collecting tests: ImportError"),
            subprocess.CompletedProcess([], 5, "deselected", ""),
        ]
    )
    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=lambda command, **k: next(outcomes),
        sha=lambda cwd: "abc1234",
    )

    ok, snapshot = session.run(cwd=_workspace(tmp_path))

    assert ok is False
    assert "ImportError" in snapshot


def test_tier_one_runs_the_repo_root_tests_ci_runs(tmp_path: Path) -> None:
    """A root tests/ belongs to no member, so tier 1 would skip it and CI
    would be the first to fail."""
    from agent_build_kit.profiles.python_uv import PROFILE

    repo = _workspace(tmp_path)
    (repo / "tests").mkdir()

    commands = PROFILE.test_commands(repo, ["tests/test_stack_config.py"], root_extras=["pyyaml"])

    assert [
        "uv",
        "run",
        "--no-project",
        "--isolated",
        "--with",
        "pytest",
        "--with",
        "pyyaml",
        "pytest",
        "tests",
        "-q",
    ] in commands


def test_tier_two_deploys_the_branch_onto_the_dev_stack_when_the_repo_has_one(
    tmp_path: Path,
) -> None:
    """The live stack runs main: a unit's deployment-config tests could only
    pass once its branch was deployed, onto the stack the consumer depends
    on. The dev stack runs the branch without touching the live one."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")
    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)
        stdout = "5 passed in 6.00s" if command[-1] == "test" else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    session = Tier2Session(
        unit(tier="tier2"), lock=tmp_path / "t2.lock", run=run, sha=lambda cwd: "abc1234"
    )
    ok, snapshot = session.run(cwd=tmp_path)

    assert [c[-1] for c in commands] == ["up", "test", "down"]
    assert ok and "5 passed" in snapshot


def test_the_dev_stack_comes_down_even_when_it_fails_to_come_up(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")
    commands: list[list[str]] = []

    def run(command, **kwargs):
        commands.append(command)
        failed = command[-1] == "up"
        return subprocess.CompletedProcess(command, 1 if failed else 0, "", "build failed")

    session = Tier2Session(
        unit(tier="tier2"), lock=tmp_path / "t2.lock", run=run, sha=lambda cwd: "abc1234"
    )
    ok, snapshot = session.run(cwd=tmp_path)

    assert [c[-1] for c in commands] == ["up", "down"], "no test, but always down"
    assert ok is False and "build failed" in snapshot


def _dev_stack(path: Path) -> Path:
    (path / "scripts").mkdir(parents=True)
    (path / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")
    return path


def test_a_dev_stack_that_attaches_to_another_comes_up_on_top_of_it(tmp_path: Path) -> None:
    """app's dev stack joins platform's dev network and needs its event
    bus, so an app unit's tier 2 brings platform's up first — and takes it
    down last, whatever happens in between."""
    base, tree = _dev_stack(tmp_path / "base"), _dev_stack(tmp_path / "tree")
    calls: list[tuple[str, str]] = []

    def run(command, *, cwd, **kwargs):
        calls.append((Path(cwd).name, command[-1]))
        stdout = "3 passed in 1.00s" if command[-1] == "test" else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=run,
        sha=lambda cwd: "abc1234",
        under=lambda: base,
    )
    ok, _ = session.run(cwd=tree)

    assert calls == [
        ("base", "up"),
        ("tree", "up"),
        ("tree", "test"),
        ("tree", "down"),
        ("base", "down"),
    ]
    assert ok


def test_when_the_stack_underneath_fails_to_come_up_nothing_is_built_on_it(
    tmp_path: Path,
) -> None:
    base, tree = _dev_stack(tmp_path / "base"), _dev_stack(tmp_path / "tree")
    calls: list[tuple[str, str]] = []

    def run(command, *, cwd, **kwargs):
        calls.append((Path(cwd).name, command[-1]))
        failed = Path(cwd).name == "base" and command[-1] == "up"
        return subprocess.CompletedProcess(command, int(failed), "", "event bus unhealthy")

    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=run,
        sha=lambda cwd: "abc1234",
        under=lambda: base,
    )
    ok, snapshot = session.run(cwd=tree)

    assert calls == [("base", "up"), ("base", "down")]
    assert ok is False
    assert "event bus unhealthy" in snapshot


def test_an_app_unit_s_tier_two_runs_on_platform_s_dev_stack(tmp_path: Path) -> None:
    from agent_build_kit.pipeline.wiring import dev_stack_underneath

    inst = make_installation(
        tmp_path,
        planning={"worktree_root": str(tmp_path.parent / "trees")},
        repos={
            "platform": {
                "path": str(tmp_path / "platform"),
                "slug": "example/platform",
                "dev_stack": {"script": "scripts/dev-stack.sh"},
            },
            "app": {
                "path": str(tmp_path / "app"),
                "slug": "example/app",
                "consumes": ["platform"],
                "dev_stack": {"script": "scripts/dev-stack.sh"},
            },
        },
    )
    prepared: list[tuple] = []

    def prepare(repo, name, *, ref, root):
        prepared.append((repo, name, ref))
        return root / name

    under = dev_stack_underneath(unit(repo="app"), inst, prepare=prepare)
    assert under is not None
    assert under() == inst.worktree_root / "_dev_stack_base"
    # the default branch as the remote has it: fetch_all runs every tick
    assert prepared == [(tmp_path / "platform", "_dev_stack_base", "origin/main")]

    # the consumed repo has nothing underneath it
    assert dev_stack_underneath(unit(repo="platform"), inst, prepare=prepare) is None


def test_a_rejected_commit_goes_back_to_the_build_run_s_own_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The very runner the build ran as — same tools, same policy hook — not
    one scoped differently that a later refactor handed the fix round."""
    from agent_build_kit.pipeline import wiring

    inst = make_installation(
        tmp_path,
        planning={"worktree_root": str(tmp_path.parent / "trees")},
        repos={"app": {"path": str(tmp_path / "app"), "slug": "example/app"}},
    )
    fixes: list[object] = []
    real = wiring.build_commit

    def recording_build_commit(**kwargs):
        fixes.append(kwargs.get("fix"))
        return real(**kwargs)

    monkeypatch.setattr(wiring, "build_commit", recording_build_commit)

    runner = wiring.build_runner(
        unit(repo="app"), store=UnitStore(tmp_path / "units.json"), installation=inst
    )

    assert fixes == [runner.run_claude]


def test_a_base_that_moved_while_the_unit_built_is_reported(tmp_path: Path) -> None:
    """Read from the store at each step: the poll that records a parent's
    merge runs between builds, while this one is still going."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1"), unit("add-marker/2", depends_on=("add-marker/1",))])
    store.set_state("add-marker/1", IN_REVIEW, pr=1, branch="spec/add-marker/1")
    base_moved = build_base_moved(store)
    child = store.get("add-marker/2")

    assert base_moved(child, "spec/add-marker/1", tree=tmp_path, start="") == ""

    store.set_state("add-marker/1", MERGED)

    assert "spec/add-marker/1 to main" in base_moved(
        child, "spec/add-marker/1", tree=tmp_path, start=""
    )


def test_a_base_rewritten_under_the_same_name_while_the_unit_built_is_reported(
    tmp_path: Path,
) -> None:
    """The parent's own parent merged mid-pass and the parent was restacked:
    still reviewed, still the same branch name, but no longer the commits the
    child is built on. Only the tip the run started on can tell."""
    repo = init_repo(tmp_path / "r")

    def commit(name: str) -> None:
        (repo / name).write_text(name)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", name)

    commit("base.txt")
    git(repo, "checkout", "-q", "-b", "spec/add-marker/1")
    commit("parent.txt")
    git(repo, "checkout", "-q", "main")
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1"), unit("add-marker/2", depends_on=("add-marker/1",))])
    store.set_state("add-marker/1", IN_REVIEW, pr=1, branch="spec/add-marker/1")
    base_moved = build_base_moved(store)
    child = store.get("add-marker/2")
    start = tip(repo, "spec/add-marker/1")

    # advanced: a parent's later round on top of what the child has
    git(repo, "checkout", "-q", "spec/add-marker/1")
    commit("parent-round-2.txt")
    assert base_moved(child, "spec/add-marker/1", tree=repo, start=start) == ""

    # rewritten: the restack force-moves it onto a main that has moved on
    git(repo, "checkout", "-q", "main")
    commit("merged-grandparent.txt")
    git(repo, "branch", "-f", "spec/add-marker/1", "main")
    reason = base_moved(child, "spec/add-marker/1", tree=repo, start=start)
    assert "spec/add-marker/1 was rewritten" in reason


def test_upstream_incomplete_looks_through_a_satisfied_unit(tmp_path: Path) -> None:
    """add-marker/2 is satisfied on add-marker/1's branch, so add-marker/3
    reads it as reviewed and carries on — even though add-marker/1, what
    add-marker/2 was really built on, was requeued after going back."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            unit("add-marker/1"),
            unit("add-marker/2", depends_on=("add-marker/1",)),
            unit("add-marker/3", depends_on=("add-marker/2",)),
        ]
    )
    store.set_state("add-marker/2", SATISFIED)
    store.set_state("add-marker/1", RUNNING)

    reason = build_upstream_incomplete(store)(store.get("add-marker/3"))

    assert "add-marker/1" in reason


def test_branch_commits_raises_on_an_unresolvable_base(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "commit", "-q", "--allow-empty", "-m", "root")

    with pytest.raises(subprocess.CalledProcessError):
        branch_commits(repo, "no-such-ref")


def test_branch_commits_counts_what_the_branch_adds(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    git(repo, "commit", "-q", "--allow-empty", "-m", "root")
    assert branch_commits(repo, "main") == 0

    git(repo, "checkout", "-q", "-b", "work")
    git(repo, "commit", "-q", "--allow-empty", "-m", "one")

    assert branch_commits(repo, "main") == 1


# --- tier 1 in a repo whose projects are not at its root ----------------------------


def recorder():
    calls: list[tuple[list[str], Path]] = []

    def run(command, cwd, **kwargs):
        calls.append((list(command), Path(cwd)))
        return subprocess.CompletedProcess(command, 0, "", "")

    return run, calls


def test_a_nested_project_s_checks_run_inside_it(tmp_path: Path) -> None:
    """The failure this fixes: `uv run pre-commit` at the repo root, where the
    repo declares no Python project, cannot find pre-commit at all — so a unit
    dies on tooling rather than on its own work."""
    run, calls = recorder()
    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: ["pipelines/poc/functions/a.py"],
        projects=[ProjectConfig(path="pipelines/poc", languages=["python"], profile="python-uv")],
    )

    passed, _ = tier1(cwd=tmp_path, base="origin/dev")

    assert passed
    assert calls, "something ran"
    assert all(at == tmp_path / "pipelines" / "poc" for _, at in calls), [str(a) for _, a in calls]


def test_each_project_is_checked_where_it_lives(tmp_path: Path) -> None:
    """A service with a second project beneath it: one diff can touch both, and
    each is checked in its own directory."""
    run, calls = recorder()
    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: ["poc/functions/a.py", "poc/tools/b.py"],
        projects=[
            ProjectConfig(path="poc", languages=["python"], profile="python-uv"),
            ProjectConfig(path="poc/tools", languages=["python"], profile="python-uv"),
        ],
    )

    tier1(cwd=tmp_path, base="origin/dev")

    where = {at for _, at in calls}
    assert tmp_path / "poc" in where
    assert tmp_path / "poc" / "tools" in where


def test_a_project_whose_toolchain_is_unimplemented_holds_the_unit(tmp_path: Path) -> None:
    """`node-npm` is declared and not implemented. Tier 1 cannot judge such a
    project, so the profile raises and `cli/pipeline.build_unit` turns that into a
    held unit — which is the honest answer, where passing it unchecked is not."""
    run, _ = recorder()
    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: ["web/src/b.ts"],
        projects=[ProjectConfig(path="web", languages=["typescript"], profile="node-npm")],
    )

    with pytest.raises(NotImplementedError):
        tier1(cwd=tmp_path, base="origin/dev")


def test_a_file_belongs_to_the_deepest_project_that_holds_it(tmp_path: Path) -> None:
    """`poc/web/src/b.ts` is inside `poc` too; the web app is what owns it."""
    run, calls = recorder()
    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: ["poc/web/src/b.ts"],
        projects=[
            ProjectConfig(path="poc", languages=["python"], profile="python-uv"),
            ProjectConfig(path="poc/web", languages=["python"], profile="python-uv"),
        ],
    )

    tier1(cwd=tmp_path, base="origin/dev")

    assert {at for _, at in calls} == {tmp_path / "poc" / "web"}


def test_a_repo_that_declares_no_projects_behaves_as_before(tmp_path: Path) -> None:
    """Every installation written before projects existed keeps working, and
    its checks keep running at the repo root."""
    run, calls = recorder()
    tier1 = build_tier1(run=run, changed=lambda cwd, base: ["src/a.py"])

    tier1(cwd=tmp_path, base="origin/main")

    assert {at for _, at in calls} == {tmp_path}


def test_a_file_outside_every_project_never_gets_a_run_at_the_repo_root(tmp_path: Path) -> None:
    """The root of a repo that declares its projects is not one of them. A
    linter run there finds no config and fails outright — which is what stopped
    a unit whose only mistake was updating docs that live above the project.

    A lint command takes a ref range, not a list of paths, so the project's own
    run already sees every file in the diff, docs included. There is nothing for
    a root run to add."""
    run, calls = recorder()
    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: ["poc/tests/test_a.py", "docs/guide.md"],
        projects=[ProjectConfig(path="poc", languages=["python"], profile="python-uv")],
    )

    passed, _ = tier1(cwd=tmp_path, base="origin/dev")

    assert passed
    assert {at for _, at in calls} == {tmp_path / "poc"}, "only where the toolchain lives"


def test_a_diff_of_nothing_but_outside_files_still_runs_the_declared_toolchain(
    tmp_path: Path,
) -> None:
    """A unit that only touched a README must not pass with nothing having run.
    The declared project's lint runs over the diff, which is where that README's
    hooks (whitespace, line endings, whatever the config says) actually live."""
    run, calls = recorder()
    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: ["README.md"],
        projects=[ProjectConfig(path="poc", languages=["python"], profile="python-uv")],
    )

    passed, _ = tier1(cwd=tmp_path, base="origin/dev")

    assert passed
    assert calls, "something ran"
    assert {at for _, at in calls} == {tmp_path / "poc"}


def test_an_empty_diff_in_a_repo_with_projects_runs_them_not_the_root(tmp_path: Path) -> None:
    run, calls = recorder()
    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: [],
        projects=[ProjectConfig(path="poc", languages=["python"], profile="python-uv")],
    )

    tier1(cwd=tmp_path, base="origin/dev")

    assert {at for _, at in calls} == {tmp_path / "poc"}


def test_a_failing_project_stops_the_unit(tmp_path: Path) -> None:
    def run(command, cwd, **kwargs):
        code = 1 if "tools" in str(cwd) else 0
        return subprocess.CompletedProcess(command, code, "", "a real failure")

    tier1 = build_tier1(
        run=run,
        changed=lambda cwd, base: ["poc/a.py", "poc/tools/b.py"],
        projects=[
            ProjectConfig(path="poc", languages=["python"], profile="python-uv"),
            ProjectConfig(path="poc/tools", languages=["python"], profile="python-uv"),
        ],
    )

    passed, output = tier1(cwd=tmp_path, base="origin/dev")

    assert not passed
    assert "a real failure" in output


def test_tier_two_runs_the_live_stack_tests_with_the_verify_env(tmp_path: Path) -> None:
    """The live-stack tests need what `verify.env` provides in a unit's tier 2
    as much as after its merge; without it an acceptance test failed at setup
    however the unit was built."""
    seen: list[dict] = []

    def run(command, **kwargs):
        seen.append(kwargs.get("env") or {})
        return subprocess.CompletedProcess([], 0, "1 passed in 1.00s", "")

    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=run,
        sha=lambda cwd: "abc1234",
        env={"ACCEPTANCE_AGENT": "agent acp"},
    )

    ok, _ = session.run(cwd=_workspace(tmp_path))

    assert ok
    assert seen and all(env.get("ACCEPTANCE_AGENT") == "agent acp" for env in seen)
    assert all("PATH" in env for env in seen)
