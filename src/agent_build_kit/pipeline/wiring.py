"""The real implementations behind `UnitRunner`'s steps.

`stack_runner` holds the sequence and nothing else; these are the callables it
sequences, and the last place where a mistake reaches a real repository. Each
is built by a small factory so the runner can be assembled with real ones in
production and recorders in tests.

Two guarantees are enforced here rather than trusted to the prompt:

- **Every Claude run carries the policy hook and a deny list.** The hook is
  the real control, but the tool restriction is passed too, so a broken hook
  is not the only thing standing between an unattended agent and
  `gh pr merge`.
- **Every push carries the SHA we last recorded.** A bare lease compares
  against a remote-tracking ref that a fetch in the same run may have already
  advanced past somebody else's commit.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from functools import partial
from pathlib import Path

from agent_build_kit import forges, profiles
from agent_build_kit.config import RepoConfig, active, active_root, models
from agent_build_kit.forges import OpensPullRequests, PostsStatuses, RepoId
from agent_build_kit.hooks.policy import hook_settings
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.claude_stream import STREAM_FLAGS, describe, final_text, stream_run
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.pr_replies import build_post_replies
from agent_build_kit.pipeline.restack import (
    Moved,
    RestackConflict,
    diff_id,
    push_with_lease,
    resolved_move,
)
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.stack_runner import Restacked, UnitRunner
from agent_build_kit.pipeline.tier2 import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    Tier2Result,
    build_snapshot,
    stack_lock,
)
from agent_build_kit.pipeline.tier2 import (
    post_status as tier2_post_status,
)
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import REVIEWED, Unit, branch_name
from agent_build_kit.pipeline.usage_guard import check_refusal, current_usage, may_start_unit
from agent_build_kit.pipeline.workspaces import prepare_detached, prepare_worktree
from agent_build_kit.profiles.base import ToolchainProfile

Run = Callable[..., subprocess.CompletedProcess]

# Passed in addition to the hook. Redundant by design: two independent things
# have to fail before the agent can merge its own PR.
DISALLOWED = (
    "Bash(gh pr merge*) Bash(git push --force *) Bash(git reset --hard*) "
    "Bash(rm -rf*) Bash(git branch -D*)"
)

# gh is read-only for agents. What they have to say on a PR the pipeline posts
# after the push (see `pr_replies`), as the account that owns the repo. The
# toolchain's own commands (a test runner, a linter) come from the profile.
ALLOWED = "Read Edit Write Grep Glob Bash(git *) Bash(gh pr view*) Bash(gh pr diff*)"


def allowed_tools(profile: ToolchainProfile) -> str:
    return f"{ALLOWED} {profile.allowed_tools}".strip()


def _specs_dir(planning_repo: Path | None) -> Path:
    root = planning_repo or active_root()
    if root is None:
        raise RuntimeError("no planning repo: load an installation (abk.yaml) first")
    return root / active().planning.specs_dir


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """The default runner the factories below accept a replacement for.

    Everything here is git, uv, docker or claude. Talking to a code host goes
    through its forge, which is the only place that knows how - there is no
    second way to reach one from the pipeline.
    """
    return subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)


def build_run_claude(
    *,
    run: Run | None = None,
    planning_repo: Path | None = None,
    model: str | None = None,
    allowed_tools: str | None = None,
    log: Callable[[str], None] | None = None,
) -> Callable[..., str]:
    """A scoped `claude -p` call inside a unit's worktree.

    Streamed: each message and tool call goes to `log` as it happens, so the
    tick log shows what a twenty-minute run is doing (see `claude_stream`).

    No `--max-budget-usd`. The session window is the real limit, and
    `usage_guard` reads it live from Anthropic rather than inferring it from a
    dollar figure somebody guessed. Carrying both means maintaining a second
    ceiling that drifts from what a unit actually costs — and guessed too low
    it refuses to start the run at all, which is what the pilot pre-flight hit
    at $0.50.
    """
    specs = _specs_dir(planning_repo)
    model = model or models().implement

    def on_event(event: dict, *, cwd: Path) -> None:
        for line in describe(event):
            # Relative to the worktree: its absolute path is the same long
            # prefix on every line and says nothing.
            (log or print)(f"  {line.replace(f'{cwd}/', '')}")

    def run_claude(prompt: str, *, cwd: Path) -> str:
        result = (run or partial(stream_run, on_event=partial(on_event, cwd=cwd)))(
            [
                "claude",
                "-p",
                prompt,
                # The specs, and nothing else in the planning repo. The
                # unit is built in the target repo's worktree but its spec
                # lives here, so some access is required — while units run in
                # the planning repo holds the run log, the unit store and
                # the pipeline's own source, none of which is an agent's
                # business. In the pilot, before worktrees moved out of this
                # repo, unit 2's agent reached into unit 1's worktree through
                # this flag and committed there under an invented unit id.
                "--add-dir",
                str(specs),
                "--settings",
                json.dumps(hook_settings(specs, branch_prefix=active().github.branch_prefix)),
                "--allowedTools",
                allowed_tools or ALLOWED,
                "--disallowedTools",
                DISALLOWED,
                "--permission-mode",
                "acceptEdits",
                "--model",
                model,
                *STREAM_FLAGS,
            ],
            cwd=cwd,
        )
        check_refusal(result)
        return final_text(result.stdout)

    return run_claude


# The reviewer reads and judges; it does not edit. Anything it wants changed it
# says, and the build step makes the change — so its judgement is not limited to
# what it can safely rewrite itself, and a concern it can only articulate
# ("this leaks under concurrency") reaches someone instead of being discarded.
REVIEW_PROMPT = """\
Review the changes on this branch against the repo's conventions in its
CLAUDE.md and against the change this unit implements.

You cannot edit anything. Report what should change and someone else will make
it, so describe each problem precisely enough to act on: what is wrong, where,
and what it should be instead. Raise what you can only observe as well as what
could be rewritten — a concern about behaviour under load, a test asserting the
wrong thing, a name that will mislead the next reader.

Hold it to the bar of work you would approve, not perfection. Style already
enforced by the linter is not worth a round trip, and nor is a preference you
could not justify to the person who wrote this.

Every round you ask for costs a rework and another review, so:

- **Find everything in one pass.** Report every problem you can see now. Do
  not hold anything back for a later round — a later round should only find
  what the next rework introduces.
- **Sweep the domain.** When you find a problem, check everything of the same
  kind before moving on: every tool taking the same arguments, every caller of
  the function, every path under the same timeout or lock. Name each instance,
  not just the first one you hit.
- **Watch for shallow interfaces.** A class or function whose public surface
  is about as complex as what it hides — a getter/setter for every field, a
  wrapper that mirrors what it wraps, a change that reaches into another
  module's internal shape instead of asking it for what it needs — costs more
  to keep than it is worth. Raise it as required when the fix is small and
  local (collapsing duplicated logic behind one private method, adding a
  named accessor instead of a raw reach-through); note it as optional, not
  required, when fixing it well means a real design decision spanning several
  callers — that is not a rework a builder should be sent back to make alone.
- **Say what done looks like.** For each required change, state the outcome
  concretely — the behaviour, the value, the test that should exist and what it
  asserts — so it can be fixed in one attempt. Where one fix is clearly best,
  prescribe it; where the fix is open, state the constraint it must meet.
- **Separate what is required from what is optional,** under those headings.
  Only required changes block approval.

**Check the tests against the real system, not against the code.** A test
passing proves only what its fakes allow. For every fake, stub or fixture
standing in for something outside this code — a library, a browser, a
service, a protocol, a data format — ask: would it still pass if the real
thing behaved differently from how the code assumes? A fake that returns what
the implementation expects (an element whose click() "counts" as a click, a
wrapper returning plain values it may not) tests the code against itself.
Required where that is the case:

- fakes at the protocol boundary — the raw wire shape the real system sends
  (CDP JSON, an HTTP body, a CLI's output) — rather than in place of a
  third-party wrapper whose behaviour is exactly what is in question;
- fixtures for parsers of external data recorded from the real system, or
  carrying everything the real one does (metadata, nulls, empty values), not
  only the fields the code reads;
- when the change is meant as a drop-in for something existing, a test of
  the workflow a caller runs (click a field, then type into it), not only of
  each call's arguments.

A later round may find a required change the builder has reported `BLOCKED:`
— its environment refused the edit (a file Claude Code protects, a permission
it does not have), not that the change was hard. If every required change left
is blocked that way and the reason holds, set `needs_human` to true and say in
`feedback` exactly what a person must change. The loop then stops and waits for
one, instead of asking the builder again for something it cannot do.

Reply with JSON and nothing else:
{"approved": true|false, "feedback": "what to change, empty when approved",
 "needs_human": false}
"""

# Read-only. The reviewer physically cannot edit the branch, so the separation
# between judging and authoring is enforced rather than asked for.
REVIEW_TOOLS = "Read Grep Glob Bash(git diff*) Bash(git log*) Bash(git show*)"


def build_run_review(
    *,
    run: Run | None = None,
    planning_repo: Path | None = None,
    model: str | None = None,
    log: Callable[[str], None] | None = None,
) -> Callable[..., str]:
    """The review pass. Separate from implementation so the standards are
    loaded only here, not during the expensive run."""
    # Its own model, not the implementation one it would otherwise inherit
    # from sharing this plumbing.
    inner = build_run_claude(
        run=run,
        planning_repo=planning_repo,
        model=model or models().review,
        allowed_tools=REVIEW_TOOLS,
        log=log,
    )

    def run_review(*, cwd: Path, context: str = "") -> str:
        # `context` is the runner's word on this branch — e.g. that it was
        # moved onto a predecessor that changed — ahead of the standing prompt.
        return inner(f"{context}\n\n{REVIEW_PROMPT}" if context else REVIEW_PROMPT, cwd=cwd)

    return run_review


class CommitRejected(RuntimeError):
    """The repo's commit gate still rejected the commit after the last attempt.

    Its message is the gate's own last output, so the unit's record says why.
    """


COMMIT_FIX_PROMPT = """\
The repo's commit gate rejected your work. This is its output, unedited:

{output}

Fix what it reports in this worktree. Do not commit, and do not skip, disable
or reconfigure the gate: the pipeline commits once you are done.
"""

# Fix rounds after the plain retry. Bounded so a gate the agent cannot satisfy
# ends as a failure rather than a loop paid for by the round.
COMMIT_FIX_ROUNDS = 2


def build_commit(
    *, unit_id: str = "", run: Run | None = None, fix: Callable[..., str] | None = None
) -> Callable[..., int]:
    """Commit whatever is staged or unstaged, reporting how many commits resulted.

    The count is what tells the runner whether the implementation run produced
    anything, which decides whether a review is worth paying for.

    A rejected commit is a fix round before it is a failure. Retried once as
    is: a gate that rewrote the files (a formatter) has already fixed them.
    Then, if it still rejects, its own output goes to `fix` — the agent that
    wrote the work, in the same worktree — a bounded number of times. Every
    attempt commits everything with the hooks on: the gate is the reason the
    pipeline may push unattended, so nothing here goes around it.
    """
    run = run or _run

    def commit(message: str, *, cwd: Path) -> int:
        # The unit id in the trailer keeps a branch's history readable without
        # the planning repo open beside it.
        body = f"{message}\n\nUnit: {unit_id}\n" if unit_id else message

        def attempt() -> subprocess.CompletedProcess | None:
            run(["git", "add", "-A"], cwd=cwd)
            if not run(["git", "diff", "--cached", "--quiet"], cwd=cwd).returncode:
                return None  # Nothing staged: an empty commit would be a lie.
            return run(["git", "commit", "-q", "-m", body], cwd=cwd)

        result = attempt()
        # The first retry carries no fix: a gate that rewrote files is done.
        for fixer in [None, *([fix] * COMMIT_FIX_ROUNDS if fix else [])]:
            if result is None or not result.returncode:
                break
            if fixer is not None:
                output = f"{result.stdout}\n{result.stderr}".strip()
                fixer(COMMIT_FIX_PROMPT.format(output=output), cwd=cwd)
            result = attempt()
        if result is None:
            return 0
        if not result.returncode:
            return 1
        # Distinct from "nothing staged" above. Both used to return 0, so a
        # rejected commit was reported to the runner as the model having
        # produced nothing, and that misdiagnosis is the whole trail an
        # unattended run leaves.
        raise CommitRejected(
            f"git commit was rejected in {cwd}:\n{result.stdout}\n{result.stderr}".strip()
        )

    return commit


def _branch_commits(repo: Path, base: str) -> int:
    """How many commits the branch carries beyond its base.

    The question a resumed unit asks: not "did this run write anything" but
    "is the work there".
    """
    result = git(repo, "rev-list", "--count", f"{base}..HEAD", check=False)
    return int(result.stdout.strip() or 0)


def _changed_files(repo: Path, base: str) -> list[str]:
    result = git(repo, "diff", "--name-only", f"{base}...HEAD", check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


def build_tier1(
    *,
    run: Run | None = None,
    changed: Callable[..., list[str]] | None = None,
    profile: ToolchainProfile | None = None,
    root_extras: list[str] | None = None,
) -> Callable[..., tuple[bool, str]]:
    """Lint the unit's own diff, then test the members it reaches.

    Everything CI will run anyway, run locally first so a failure costs
    seconds rather than a push, a CI round trip and a red PR.

    **Scoped to the unit, not the repo.** Linting every file fails a unit for
    problems in files it never touched: the pilot's first unit died on a
    pre-existing type error elsewhere while its own three files were clean.
    The profile's lint command takes the base ref for that reason.
    """
    run = run or _run
    changed = changed or _changed_files
    profile = profile or profiles.get("python-uv")

    def tier1(*, cwd: Path, base: str) -> tuple[bool, str]:
        """(passed, what failed) — the output is what makes a retry useful."""
        files = changed(cwd, base)

        result = run(profile.lint_command(base), cwd=cwd)
        if result.returncode:
            return False, f"{result.stdout}\n{result.stderr}".strip()[-4000:]

        for command in profile.test_commands(cwd, files, root_extras=root_extras or []):
            result = run(command, cwd=cwd)
            if result.returncode:
                return False, f"{result.stdout}\n{result.stderr}".strip()[-4000:]
        return True, ""

    return tier1


def _default_push(repo: Path, branch: str, last_pushed: str | None) -> str:
    return push_with_lease(repo, branch, last_pushed=last_pushed)


def build_push(store: UnitStore, *, push: Callable[..., str] | None = None) -> Callable[..., str]:
    """Push a unit's branch with the lease its own history justifies.

    The lease names the SHA *this* runner last published, which the store has
    to remember because every tick is a separate process. Recording the new
    one afterwards is what makes the next restack's push safe.
    """
    push = push or _default_push

    def do_push(branch: str, *, cwd: Path) -> str:
        unit_id = branch.removeprefix(active().github.branch_prefix)
        try:
            last_pushed = store.get(unit_id).pushed
        except KeyError:
            last_pushed = None

        sha = push(cwd, branch, last_pushed)
        try:
            store.record_push(unit_id, sha)
        except KeyError:
            pass  # A branch with no unit behind it: nothing to lease against.
        return sha

    return do_push


def build_post_status(
    *, for_repo: Callable[[str], tuple[PostsStatuses, RepoId]] | None = None
) -> Callable[[str, Tier2Result], None]:
    """Post a tier 2 result as a commit status on whichever host the repo lives on."""
    for_repo = for_repo or forges.for_repo

    def post(repo_name: str, result: Tier2Result) -> None:
        forge, repo = for_repo(repo_name)
        tier2_post_status(forge, repo, result)

    return post


def build_open_pr(
    *, for_repo: Callable[[str], tuple[OpensPullRequests, RepoId]] | None = None
) -> Callable[..., int]:
    """Create the unit's PR, or update the one it already has.

    Every restack pushes the branch again, so this runs repeatedly for one
    unit. A second create would fail outright, and the body would then never
    reflect the restack. Which host the PR is opened on is the forge's
    business; this only knows that a unit has one.
    """
    for_repo = for_repo or forges.for_repo

    def open_pr(unit: Unit, *, body: str, base: str, cwd: Path) -> int:
        forge, repo = for_repo(unit.repo)
        branch = branch_name(unit)
        number = forge.find_pr(repo, head=branch)

        if number is None:
            return forge.create_pr(
                repo, head=branch, base=base, title=f"{unit.id}: {unit.title}", body=body
            )

        forge.update_pr(repo, number, base=base, body=body)
        return number

    return open_pr


def build_worktree(
    repos: dict[str, Path],
    *,
    root: Path,
    prepare: Callable[..., Path] | None = None,
) -> Callable[[Unit, str], Path]:
    """Give a unit its own checkout of the repo it lands in.

    Units run in parallel and land in different repos, so a shared checkout
    would put two agents in one working tree. A repo we have no checkout of is
    refused here rather than three steps later, with a worktree half built.
    """
    prepare = prepare or (
        lambda repo, branch, base, tree_root: prepare_worktree(
            repo, branch, base=base, root=tree_root
        )
    )

    def worktree(unit: Unit, base: str) -> Path:
        if unit.repo not in repos:
            raise KeyError(
                f"{unit.id} targets {unit.repo}, which has no checkout configured "
                f"(known: {', '.join(sorted(repos)) or 'none'})"
            )
        return prepare(repos[unit.repo], branch_name(unit), base, root)

    return worktree


def build_may_start(*, usage: Callable[[], object] | None = None) -> Callable[[], tuple[bool, str]]:
    """The usage guard, in the shape the runner asks for.

    Checked again per unit rather than once per tick: a tick can start several
    units, and the window moves while they run.
    """
    usage = usage or current_usage

    def may_start() -> tuple[bool, str]:
        decision = may_start_unit(usage())  # pyrefly: ignore[bad-argument-type]
        return decision.may_start, decision.reason

    return may_start


class Tier2Session:
    """One unit's tier 2 run, and the status that follows it.

    The result is held between the two because they happen either side of the
    push: tier 2 has to pass before anything is published, and GitHub will not
    accept a status for a commit it has not yet seen.
    """

    def __init__(
        self,
        unit: Unit,
        *,
        lock: Path,
        run: Run | None = None,
        sha: Callable[[Path], str] | None = None,
        status: Callable[..., None] | None = None,
        timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        under: Callable[[], Path] | None = None,
        profile: ToolchainProfile | None = None,
        marker: str = "local_stack",
        dev_stack: str | None = "scripts/dev-stack.sh",
        stack_versions_command: list[str] | None = None,
    ) -> None:
        self.unit = unit
        # The checkout whose dev stack this one's attaches to, if any
        # (dev_stack_underneath).
        self._under = under
        self._profile = profile or profiles.get("python-uv")
        self._marker = marker
        # The repo's dev stack script, with `up`, `test` and `down`: tier 2
        # runs the unit's branch on it rather than on the live stack, which
        # runs the default branch. None means the repo has no dev stack.
        self._dev_stack = Path(dev_stack) if dev_stack else None
        self._stack_versions_command = stack_versions_command
        self.lock = lock
        self._run = run or _run
        self._sha = sha or _head_sha
        self._status = status or build_post_status()
        self._timeout = timeout
        self.result: Tier2Result | None = None

    def run(self, *, cwd: Path) -> tuple[bool, str]:
        if self._dev_stack is not None and (cwd / self._dev_stack).is_file():
            return self._run_on_dev_stack(cwd, self._dev_stack)
        commands = self._profile.tier2_commands(cwd, marker=self._marker)
        sha = self._sha(cwd)
        passed = failed = skipped = 0
        duration = 0.0
        outputs: list[str] = []

        # A queue, not a fail-fast lock: a second unit's tier 2 tests are
        # perfectly valid, there is simply one local stack to run them on.
        with stack_lock(self.lock, self._timeout):
            for command in commands:
                completed = self._run(command, cwd=cwd)
                out = f"{completed.stdout or ''}{completed.stderr or ''}"
                p, f, s, d = self._profile.parse_test_summary(out)
                # A zero exit code with no counts parsed is still a pass, and so
                # is "no tests collected" — a member with no live-stack tests. Any
                # other non-zero exit is a failure even if no summary printed.
                nothing = self._profile.no_tests_collected_exit
                if completed.returncode not in (0, nothing) and not f:
                    f = 1
                passed, failed, skipped, duration = (
                    passed + p,
                    failed + f,
                    skipped + s,
                    duration + d,
                )
                if f or completed.returncode not in (0, nothing):
                    outputs.append(f"$ {' '.join(command)}\n{out}")
                elif p:
                    outputs.append(f"$ {' '.join(command)}\n{out[-1500:]}")

        output = "\n\n".join(outputs)
        command = " && ".join(" ".join(c) for c in commands)

        self.result = Tier2Result(
            sha=sha,
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_seconds=duration,
            command=command,
            output=output[-4000:],
            stack_versions=_stack_versions(self._stack_versions_command, run=self._run),
        )
        return self.result.ok, build_snapshot(self.result)

    def _run_on_dev_stack(self, cwd: Path, script: Path) -> tuple[bool, str]:
        """Deploy this branch onto the dev stack, test against it, take it down.

        The live stack runs the default branch, so a unit that changes
        deployment config — a published port, a gateway registration — can
        only pass tier 2 against a stack running its own branch. The dev stack
        is that, and cannot touch the live one. It is torn down whatever
        happens, so the next unit starts from its own branch.
        """
        sha = self._sha(cwd)
        up = [str(script), "up"]
        test = [str(script), "test"]
        down = [str(script), "down"]
        with stack_lock(self.lock, self._timeout):
            base = self._under() if self._under else None
            try:
                beneath = self._run(up, cwd=base) if base else None
                if beneath is not None and beneath.returncode:
                    completed, command = beneath, up
                else:
                    try:
                        started = self._run(up, cwd=cwd)
                        if started.returncode:
                            completed, command = started, up
                        else:
                            completed, command = self._run(test, cwd=cwd), test
                    finally:
                        self._run(down, cwd=cwd)
            finally:
                if base:
                    self._run(down, cwd=base)

        output = f"{completed.stdout or ''}{completed.stderr or ''}"
        passed, failed, skipped, duration = self._profile.parse_test_summary(output)
        if completed.returncode and not failed:
            failed = 1
        self.result = Tier2Result(
            sha=sha,
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_seconds=duration,
            command=f"{script} up && {script} test (then down)"
            if command == test
            else f"{script} up (failed)",
            output=output[-4000:],
            stack_versions=_stack_versions(self._stack_versions_command, run=self._run),
        )
        return self.result.ok, build_snapshot(self.result)

    def post(self, sha: str, ok: bool) -> None:
        if self.result is None:
            raise ValueError("tier 2 has not run for this unit, so there is no status to post")
        if sha != self.result.sha:
            raise ValueError(
                f"asked to post a status for {sha[:7]}, but tier 2 ran against a "
                f"different commit ({self.result.sha[:7]})"
            )
        self._status(self.unit.repo, self.result)


def _head_sha(cwd: Path) -> str:
    return git(cwd, "rev-parse", "HEAD", check=False).stdout.strip()


def _stack_versions(command: list[str] | None, *, run: Run | None = None) -> dict[str, str]:
    """What the live stack was when tier 2 ran, so the claim can be checked:
    `verify.stack_versions_command`'s output, one `name<TAB>image` per line.
    None records nothing."""
    if not command:
        return {}
    result = (run or _run)(list(command))
    versions: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, image = line.partition("\t")
        if name and image:
            versions[name.strip()] = image.strip()
    return versions


def _own_work_starts_after(tree: Path, base: str, unit: Unit, store: UnitStore) -> str:
    """The commit this unit's own work begins after: what a replay starts from.

    Usually where it and its base last shared history. But a parent that was
    squash-merged reaches the trunk as one new commit, so the unit still
    carries the parent's original commits and they share nothing newer with
    the trunk: replaying from there re-applies all of the parent's old
    commits on top of its squashed final form, and the conflict resolver
    fights two versions of the same code. Where the unit forked from a parent's
    branch is later than that, and is where its own work really starts — found
    from the parent's branch, or the last commit it pushed or had approved,
    since a merged parent's branch may already be deleted.
    """
    start = git(tree, "merge-base", base, "HEAD", check=False).stdout.strip()
    index = {u.id: u for u in store.all()}
    for dep in unit.depends_on:
        parent = index.get(dep)
        if parent is None or parent.repo != unit.repo:
            continue
        for ref in (parent.branch, parent.pushed, parent.approved):
            if not ref:
                continue
            fork = git(tree, "merge-base", ref, "HEAD", check=False).stdout.strip()
            # Later than what we have, and on this branch's own line.
            if fork and (not start or _is_ancestor(tree, start, fork)):
                start = fork
                break
    return start


def build_restack_onto(store: UnitStore, *, move: Callable[..., Moved] | None = None):
    """Move a resuming unit's branch onto its base, if the base has moved.

    Reuses `move_branch_onto` — the primitive, with its LLM conflict resolution
    and its check that the resolution did not simply delete one side — rather
    than `events.build_restack`, which also pushes, retargets the PR and
    comments. A resuming unit is not ready to push: it still has a review loop
    and tier 1 ahead of it.

    "Has the base moved" is whether the base's tip is still an ancestor of this
    branch. If it is, nothing to do — and a rebase would be actively harmful,
    since it rewrites every commit and invalidates any check already run.
    """
    move = move or resolved_move

    def restack_onto(*, tree: Path, branch: str, base: str, unit: Unit) -> Restacked | None:
        if _is_ancestor(tree, base):
            return None

        old_base = _own_work_starts_after(tree, base, unit, store)
        if not old_base:
            return None

        # Named for the resolver and the reviewer: the predecessor that moved.
        onto = _predecessor(unit, base, store)
        onto_unit = onto.id if onto else base
        onto_intent = onto.title if onto else "the updated base"
        old_head = git(tree, "rev-parse", "HEAD").stdout.strip()
        approved = store.get(unit.id).approved
        try:
            moved = move(
                tree,
                branch,
                new_base=base,
                old_base=old_base,
                moving_unit=unit.id,
                moving_intent=unit.title,
                onto_unit=onto_unit,
                onto_intent=onto_intent,
            )
        except RestackConflict as error:
            # Not a failure: the adapt step ports the work by hand. It needs
            # to know which tests the previous work had, to account for each.
            return Restacked(
                onto_unit=onto_unit,
                onto_intent=onto_intent,
                old_base=old_base,
                old_head=old_head,
                conflict=str(error),
                old_tests=tuple(_tests_added(tree, old_base, old_head)),
            )

        # Applied cleanly with the unit's own diff byte-for-byte unchanged: the
        # review that approved it still stands, as after a parent's merge.
        if (
            not moved.resolved
            and approved == old_head
            and diff_id(tree, old_base, old_head) == diff_id(tree, base, moved.sha)
        ):
            store.record_approval(unit.id, moved.sha)

        return Restacked(
            onto_unit=onto_unit,
            onto_intent=onto_intent,
            old_base=old_base,
            old_head=old_head,
            resolved=moved.resolved,
        )

    return restack_onto


def _predecessor(unit: Unit, base: str, store: UnitStore) -> StoredUnit | None:
    """The unit this one is built on: the base's own unit, or — when the base
    is the trunk because the parent merged — the same-repo parent it depends on."""
    units = store.all()
    by_branch = next((u for u in units if u.branch and u.branch == base), None)
    if by_branch is not None:
        return by_branch
    index = {u.id: u for u in units}
    parents = [index[d] for d in unit.depends_on if d in index and index[d].repo == unit.repo]
    return parents[-1] if parents else None


TEST_DEF = re.compile(r"^\+\s*(?:async\s+)?def\s+(test_\w+)", re.M)


def _tests_added(tree: Path, old_base: str, old_head: str) -> list[str]:
    """Test functions the unit's previous work added or changed."""
    diff = git(tree, "diff", old_base, old_head, "--", "*.py", check=False).stdout
    return sorted(set(TEST_DEF.findall(diff)))


def _tests_in(tree: Path) -> set[str]:
    """Every test function in the worktree as it stands."""
    out = git(tree, "grep", "-hoE", "def test_[A-Za-z0-9_]+", "--", "*.py", check=False).stdout
    return {line.removeprefix("def ").strip() for line in out.splitlines() if line.strip()}


def _reset_to(tree: Path, onto: str, keep: str) -> None:
    """Keep the current work under `keep`, then put the branch on `onto`.

    A ref rather than a branch: it is there for the adapt step to read from,
    not to be built on or pushed, and a branch would clutter the checkout.
    """
    git(tree, "update-ref", keep, "HEAD")
    git(tree, "reset", "--hard", "-q", onto)


def _is_ancestor(tree: Path, base: str, of: str = "HEAD") -> bool:
    return not git(tree, "merge-base", "--is-ancestor", base, of, check=False).returncode


def build_upstream_incomplete(store: UnitStore) -> Callable[..., str]:
    """Why a unit should stop, if something it is built on went back.

    Read from the store each time rather than captured once: the poller that
    requeues an upstream unit runs in a different process from the build that
    has to notice, and the store is the only thing they share.

    Only same-repo parents. A cross-repo dependency is an ordering constraint
    that is already satisfied by a merge, not a branch this unit sits on, so it
    cannot move underneath it.
    """

    def upstream_incomplete(unit: Unit) -> str:
        known = {u.id: u for u in store.all()}
        for dep in unit.depends_on:
            parent = known.get(dep)
            if parent and parent.repo == unit.repo and parent.state not in REVIEWED:
                return f"{dep} is {parent.state} — it went back after this unit started"
        return ""

    return upstream_incomplete


def dev_stack_underneath(
    unit: Unit,
    installation: Installation,
    *,
    prepare: Callable[..., Path] = prepare_detached,
) -> Callable[[], Path] | None:
    """Where the dev stack this unit's repo attaches to comes up from, if any.

    A repo whose dev stack joins another's network needs that one up first
    (`consumes`, in abk.yaml), so its tier 2 runs on top of it — from the
    default branch as the remote has it (fetch_all runs every tick), never
    the user's own checkout.
    """
    base = installation.dev_stack_base(unit.repo)
    if base is None:
        return None
    ref = f"origin/{installation.repo(base).default_branch}"
    return lambda: prepare(
        installation.checkouts[base], "_dev_stack_base", ref=ref, root=installation.worktree_root
    )


def build_runner(
    unit: Unit,
    *,
    store: UnitStore,
    installation: Installation,
    log: Callable[[str], None] = print,
) -> UnitRunner:
    """Assemble the runner for one unit, with every step bound to reality.

    Per unit rather than once: the commit trailer, the tier 2 session and the
    status all belong to this unit and nothing else.
    """
    repo: RepoConfig = installation.repo(unit.repo)
    profile = profiles.get(repo.profile)
    root = installation.state_dir
    tier2 = Tier2Session(
        unit,
        lock=root / "tier2.lock",
        under=dev_stack_underneath(unit, installation),
        profile=profile,
        marker=repo.tests.tier2_marker,
        dev_stack=repo.dev_stack.script if repo.dev_stack else None,
        stack_versions_command=installation.config.verify.stack_versions_command,
    )
    planning_repo = installation.root
    # Units build in parallel, and two in one repo share its `.git`. Adding a
    # worktree and pushing both take git's own locks there, which fail rather
    # than wait — so those two steps take turns per repo. Everything else
    # happens inside the unit's own worktree and needs no turn-taking.
    repo_turn = partial(file_lock, root / "locks" / f"repo-{unit.repo}.lock")
    worktree = build_worktree(installation.checkouts, root=installation.worktree_root)
    push = build_push(store)

    def worktree_in_turn(unit: Unit, base: str) -> Path:
        with repo_turn():
            return worktree(unit, base)

    def push_in_turn(branch: str, *, cwd: Path) -> str:
        with repo_turn():
            return push(branch, cwd=cwd)

    tools = allowed_tools(profile)
    run_claude = build_run_claude(planning_repo=planning_repo, allowed_tools=tools, log=log)
    return UnitRunner(
        store=store,
        planning_repo=planning_repo,
        worktree=worktree_in_turn,
        reset_to=_reset_to,
        tests_in=_tests_in,
        may_start=build_may_start(),
        run_claude=run_claude,
        run_rework=build_run_claude(
            planning_repo=planning_repo, model=models().rework, allowed_tools=tools, log=log
        ),
        run_review=build_run_review(planning_repo=planning_repo, log=log),
        run_rework_review=build_run_review(
            planning_repo=planning_repo, model=models().rework_review, log=log
        ),
        # A rejected commit goes back to the build run's agent, same policy.
        commit=build_commit(unit_id=unit.id, fix=run_claude),
        branch_commits=_branch_commits,
        upstream_incomplete=build_upstream_incomplete(store),
        restack_onto=build_restack_onto(store),
        run_tier1=build_tier1(profile=profile, root_extras=repo.tests.root_extras),
        run_tier2=tier2.run,
        push=push_in_turn,
        open_pr=build_open_pr(),
        post_status=tier2.post,
        reply=build_post_replies(root=root, log=log),
        head=_head_sha,
        log=log,
    )
