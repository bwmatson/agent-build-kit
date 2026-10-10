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

import ast
import logging
import os
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from agent_build_kit import forges, infra, profiles, runtimes
from agent_build_kit.config import (
    CONFIG_ENV,
    CONFIG_FILENAME,
    ProjectConfig,
    RepoConfig,
    active,
    active_root,
    models,
    stack_versions_for,
)
from agent_build_kit.forges import FileChange, Forge, RegistersStacks, RepoId, StackRefused
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.changelog_convention import review_changelog_paragraph
from agent_build_kit.pipeline.command_limit import run_limited
from agent_build_kit.pipeline.environment import (
    artifact_patterns,
    lock_paths,
    restore_unchanged_locks,
    unstage_artifacts,
    unstage_untracked_locks,
)
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.flakes import Flake, FlakeFound, flake_record, wait_on_fix
from agent_build_kit.pipeline.gateway_usage import Spend, attribution, configured_source
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.pr_replies import (
    MARKER,
    build_post_replies,
    own_posts,
    record_given_comments,
)
from agent_build_kit.pipeline.restack import (
    HostMoved,
    Moved,
    RestackConflict,
    adopt_host_head,
    diff_id,
    move_branch_onto,
    push_with_lease,
    remote_head,
    resolved_move,
)
from agent_build_kit.pipeline.scratch import run_folder
from agent_build_kit.pipeline.shell import git, git_out, has_origin
from agent_build_kit.pipeline.stack_runner import Restacked, UnitRunner, Worktree
from agent_build_kit.pipeline.tier2 import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    Tier2Result,
    build_snapshot,
    stack_lock,
)
from agent_build_kit.pipeline.tier2 import (
    post_status as tier2_post_status,
)
from agent_build_kit.pipeline.transcript import Transcript, transcript_dir
from agent_build_kit.pipeline.ui_review import ui_notes_of, ui_reply_writer, unit_patch_of
from agent_build_kit.pipeline.unit_size import actual_lines, over_ceiling
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    PLANNED,
    REVIEWED,
    Unit,
    base_of,
    branch_name,
    local_ref,
    through_satisfied,
    trunk_of,
)
from agent_build_kit.pipeline.usage_guard import (
    Decision,
    UsageReading,
    current_usage,
    decide_start,
    may_start_unit,
)
from agent_build_kit.pipeline.vocabulary import effective_state
from agent_build_kit.pipeline.workspaces import BranchBusy, prepare_detached, prepare_worktree
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.runtimes import AgentRequest, AgentRuntime, ToolPolicy
from agent_build_kit.runtimes.base import Role, SessionUnavailable
from agent_build_kit.runtimes.claude_code import through

logger = logging.getLogger(__name__)

Run = Callable[..., subprocess.CompletedProcess]

# How many times the failed tests are run again, alone, before they count as a flake.
FLAKE_RERUNS = 2

# Told a finished agent call: `(result, *, role, model, runtime)`, and `gateway`
# (a function giving the run's `Spend`) when a gateway key was minted for it.
AgentCallback = Callable[..., None]

# The code host is read-only for agents: the forge names the commands that read
# a PR (`read_commands`). What they have to say on a PR the pipeline posts after
# the push (see `pr_replies`), as the account that owns the repo. The
# toolchain's own commands (a test runner, a linter) come from the profile.
BASE_TOOLS = "Read Edit Write Grep Glob Bash(git *)"


def forge_read_tools(forge: Forge) -> str:
    return " ".join(f"Bash({' '.join(command)}*)" for command in forge.read_commands)


def allowed_tools(profile: ToolchainProfile, forge: Forge) -> str:
    return f"{BASE_TOOLS} {forge_read_tools(forge)} {profile.allowed_tools}".strip()


def _specs_dir(planning_repo: Path | None) -> Path:
    root = planning_repo or active_root()
    if root is None:
        raise RuntimeError("no planning repo: load an installation (abk.yaml) first")
    return root / active().planning.specs_dir


def _run_limited(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """The default runner for tier 1: `_run` under the configured command time limit."""
    limits = active().limits
    return run_limited(
        args,
        limit=limits.tier1_command_seconds,
        grace=limits.tier1_abort_grace_seconds,
        **kwargs,
    )


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """The default runner the factories below accept a replacement for.

    Everything here is git, a toolchain command or docker; an agent is reached through its
    runtime. Talking to a code host goes
    through its forge, which is the only place that knows how - there is no
    second way to reach one from the pipeline.
    """
    return subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)


class AgentPushed(RuntimeError):
    """The unit's branch on the remote changed while an agent step ran."""


def _unit_branch(cwd: Path) -> str:
    """The unit branch `cwd` has checked out, or "" for any other work."""
    if not cwd.is_dir():
        return ""
    here = git(cwd, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    return here if here.startswith(active().git.branch_prefix) else ""


def _agent_pushed(cwd: Path, branch: str, before: str | None) -> str | None:
    """The head the agent pushed during the step, or None when nothing says it did.

    Only a head this worktree's own branch contains counts: one it has no
    commit for was pushed from elsewhere (a person, the host's update-branch),
    and one the agent merely fetched into the object store is not on its
    branch. Neither is the agent's push. An unreadable remote, on either side,
    says nothing.
    """
    after = remote_head(cwd, branch)
    if before is None or not after or after == before:
        return None
    ancestor = git(cwd, "merge-base", "--is-ancestor", after, "HEAD", check=False)
    return None if ancestor.returncode else after


INTERRUPTED_PROMPT = (
    "The process running you was interrupted and has been restarted; this is the same "
    "session, continued. Re-read the worktree (git status, git log, the files you were "
    "changing) before trusting your memory of it, then finish the task you were given."
)


def _recorder(
    record_for: tuple[Unit, Path, datetime] | None, place: str, role: Role
) -> Transcript | None:
    """The file this call's events go to, named by the node and round that made it.

    `place` is `<unit>:<node>:<round>` (gateway_usage.attribution); a call made
    outside a node is recorded under its role, in round 0.
    """
    if record_for is None:
        return None
    unit, directory, started = record_for
    _, _, rest = place.partition(":")
    node, _, number = rest.rpartition(":")
    return Transcript(
        directory,
        unit,
        node=node or role,
        round=int(number) if number.isdigit() else 0,
        started=started,
        result_limit=active().limits.transcript_result_chars,
        runs_kept=active().limits.transcript_runs_kept,
    )


def build_run(
    *,
    run: Run | None = None,
    planning_repo: Path | None = None,
    allowed_tools: str | None = None,
    log: Callable[[str], None] | None = None,
    journal: Callable[[str], None] | None = None,
    transcript: Callable[[str], None] | None = None,
    record_for: tuple[Unit, Path, datetime] | None = None,
    runtime: AgentRuntime | None = None,
    role: Role = "implement",
) -> Callable[..., str]:
    """A scoped agent run inside a unit's worktree, policed by the hook and
    the deny list the runtime applies for a `ToolPolicy`.

    Streamed where the runtime can: each message and tool call goes to `log`
    as it happens, so the tick log shows what a twenty-minute run is doing.
    With a `transcript`, the run's own steps go to `journal` (default `log`)
    clipped to a line and to `transcript` whole. With `record_for`, a unit, the
    directory of its transcripts and its run's start, every call is recorded there as the agent
    streams (pipeline/transcript.py), under the node and round that made the call.
    `run` is the older injection point — Claude Code, run through it rather
    than the real process.

    No `--max-budget-usd`. The session window is the real limit, and
    `usage_guard` reads it live from Anthropic rather than inferring it from a
    dollar figure somebody guessed. Carrying both means maintaining a second
    ceiling that drifts from what a unit actually costs — and guessed too low
    it refuses to start the run at all, which is what the pilot pre-flight hit
    at $0.50.
    """
    specs = _specs_dir(planning_repo)
    # Half-configured gateway settings already said, once for this runner.
    warned: set[str] = set()

    def run_agent(
        prompt: str,
        *,
        cwd: Path,
        model: str = "",
        resume_session: str = "",
        follow_up: str = "",
        resume_runtime: str = "",
        on_session: Callable[[str], None] | None = None,
        on_result: AgentCallback | None = None,
    ) -> str:
        agent = runtime or (through(run) if run else runtimes.active())
        if resume_session and not agent.supports_session_resume:
            raise SessionUnavailable(f"{agent.name} cannot resume a session")
        if resume_runtime and resume_runtime != agent.name:
            raise SessionUnavailable(
                f"the session belongs to {resume_runtime}, and this call runs on {agent.name}"
            )
        # With no origin there is no push to catch: the "remote" head is the
        # worktree's own branch, which any commit moves.
        branch = _unit_branch(cwd) if has_origin(cwd) else ""
        before = remote_head(cwd, branch) if branch else None
        # A key of its own for this call, where a gateway is configured: its
        # totals reach the callback beside what the agent reports, and it is
        # revoked however the call ends.
        place = attribution.get()
        source = configured_source(log or print, warned) if on_result and place else None
        if source is not None and not agent.passes_env:
            (log or print)(
                f"gateway: {agent.name} cannot pass a key to its agent; "
                "the gateway source is skipped"
            )
            source = None
        env: dict[str, str] = {}
        handle: object = None
        if source is not None:
            env, handle = source.begin(place)
        # Where the installation's abk.yaml is, for the `abk` commands an agent may run from a
        # worktree that sits outside the planning repo.
        if (root := active_root()) is not None:
            env = {**env, CONFIG_ENV: str(root / CONFIG_FILENAME)}
        spent: list[Spend] = []

        def spend() -> Spend:
            if source is not None and not spent:
                spent.append(source.finish(handle))
            return spent[0] if spent else Spend()

        gateway = {"gateway": spend} if source is not None else {}
        recorder = _recorder(record_for, place, role)
        request = AgentRequest(
            # A continued session holds the original prompt already: it is told what is new,
            # or, when it is the node's own interrupted run, that it was interrupted.
            prompt=(follow_up or INTERRUPTED_PROMPT) if resume_session else prompt,
            resume_session=resume_session,
            on_session=on_session,
            on_result=(
                partial(on_result, role=role, model=model, runtime=agent.name, **gateway)
                if on_result
                else None
            ),
            role=role,
            cwd=cwd,
            env=env,
            # The specs, and nothing else in the planning repo. The unit
            # is built in the target repo's worktree but its spec lives
            # here, so some access is required — while the planning repo
            # holds the run log, the unit store and the pipeline's own
            # source, none of which is an agent's business. In the pilot,
            # before worktrees moved out of this repo, unit 2's agent
            # reached into unit 1's worktree through this and committed
            # there under an invented unit id.
            add_dirs=(specs,),
            model=model,
            allowed_tools=allowed_tools or BASE_TOOLS,
            permission_mode="edit",
            policy=ToolPolicy(specs_dir=specs, branch_prefix=active().git.branch_prefix),
            on_event=journal or log or print,
            on_transcript=transcript,
            on_record=recorder.record if recorder else None,
        )
        try:
            # Its own folder for long command output, gone when the run ends:
            # nothing one agent wrote reaches another.
            with run_folder(cwd) as out:
                if out is not None:
                    request = request.model_copy(update={"env": {**env, "ABK_OUT": str(out)}})
                result = agent.run(request)
        finally:
            spend()
        if branch and (after := _agent_pushed(cwd, branch, before)):
            # Only the pipeline pushes. A commit made in this worktree that
            # reached the remote during an agent step was pushed by the
            # agent, and would fail the pipeline's own push later, far from
            # the cause.
            raise AgentPushed(
                f"{branch} on the remote moved from {(before or 'nothing')[:9]} to {after[:9]} "
                "during an agent step, to a commit made in this worktree; the pipeline is "
                "the only pusher, so the agent pushed it"
            )
        if not result.ok:
            # Half-finished edits are on disk: carrying on would commit them.
            raise RuntimeError(result.error)
        return result.text

    return run_agent


# The reviewer reads and judges; it does not edit. Anything it wants changed it
# says, and the build step makes the change — so its judgement is not limited to
# what it can safely rewrite itself, and a concern it can only articulate
# ("this leaks under concurrency") reaches someone instead of being discarded.
REVIEW_PROMPT = """\
Review the changes on this branch against the repo's conventions in its
CLAUDE.md and against the change this unit implements.

Run your own commands (`git diff`, `git log`, `git show`) to check what you are
unsure of: nothing another agent ran or printed is shown to you, and what you
run is not shown to anyone else. If one may print a lot, redirect it into
`$ABK_OUT/` and read the file with your Read or Grep tool.

You cannot edit anything, and you never push — the pipeline does. Report what
should change and someone else will make it, so describe each problem precisely
enough to act on: what is wrong, where, and what it should be instead. Raise
what you can only observe as well as what could be rewritten — a concern about
behaviour under load, a test asserting the wrong thing, a name that will mislead the next reader.

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
- **Read the code around the change, not only the diff.** For each hunk, open
  the enclosing function and read it whole. For each removed line, ask what it
  enforced — a check, a lock, a validation, an ordering — and whether the change
  still enforces it somewhere. Follow callers and callees one step out: who
  depends on what changed, and what the changed code now assumes of what it
  calls.
- **Re-check each candidate before you report it.** Before a problem goes in
  your reply, re-read the code it points at and try to show it is wrong: is it
  handled elsewhere, does a test cover it, does the caller never do that? Drop
  what does not survive. Report what does with the evidence — the location and
  the concrete input or state that goes wrong — not a suspicion.
- **Say what done looks like.** For each required change, state the outcome
  concretely — the behaviour, the value, the test that should exist and what it
  asserts — so it can be fixed in one attempt. Where one fix is clearly best,
  prescribe it; where the fix is open, state the constraint it must meet.
- **Separate what is required from what is optional** with each finding's
  `required` field. Only required changes block approval.

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

**You may approve and still record something.** A `follow_ups` entry kinded
`"optional"` — a name that could be better, a small refactor, a doc line —
approves alongside it and is kept where the change's next unit and this PR's
reviewer will see it, instead of spending another round or being dropped.
Never kind it `"optional"` for a `correctness` problem, a `test_passes_regardless`
(a test whose fakes let it pass whatever the code does), a `missing_test` a task
asked for, or anything the command `policy` forbids — those always block,
whatever `approved` says. Deferral is for work that can wait, not for work
that is merely inconvenient to fix now. A point you already give as an optional
finding is not repeated as an `"optional"` follow-up: that list is for points
with no file to name.

**Escalate instead of spending another round when:**
- you find another instance of a kind an earlier round of this same review
  already raised, and the kind is open-ended — a list of spellings for an
  effect, not a finite set — so the next round would just find the next
  instance. Set `"escalate": "class"` and say in `reasoning` why the kind
  cannot be enumerated; a person decides how to change the approach.
- the builder declined a point you raised, with a reason, and you still think
  it is wrong. Do not ask a third time: set `"escalate": "disagreement"` and
  say in `reasoning` why the builder's reason does not hold.

List each problem in `findings`, one entry per problem, with the `consequence`
and what `done` looks like. A required finding's consequence is the triggering
input or state and the wrong result. For a documented convention, it is the
rule and where it is written; for a test, the wrong behaviour it would let
through; for a doc, the sentence it makes false. A finding whose consequence
you cannot name is reported `required: false`. List optional findings most
important first: only the first five are kept. A
required finding blocks approval, so `approved` cannot be true while one is
listed. When an earlier round's findings are shown above, answer each earlier
required one by id in `earlier` as `fixed`, `open` or `declined` (the builder's
reason holds); leave none unanswered.

Reply with JSON and nothing else:
{"approved": true|false, "feedback": "anything that is not a finding, empty when approved",
 "findings": [{"file": "path", "line": 12, "summary": "...", "consequence": "...",
               "done": "...", "required": true|false}],
 "earlier": [{"id": "1.1", "status": "fixed|open|declined"}],
 "needs_human": false,
 "follow_ups": [{"kind": "optional|correctness|test_passes_regardless|missing_test|policy",
                 "point": "..."}],
 "escalate": "", "reasoning": ""}
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
    journal: Callable[[str], None] | None = None,
    transcript: Callable[[str], None] | None = None,
    record_for: tuple[Unit, Path, datetime] | None = None,
    runtime: AgentRuntime | None = None,
    role: Role = "review",
    forge: Forge | None = None,
    repo: RepoConfig | None = None,
) -> Callable[..., str]:
    """The review pass. Separate from implementation so the standards are
    loaded only here, not during the expensive run."""
    inner = build_run(
        run=run,
        planning_repo=planning_repo,
        # Reading its pull request is allowed (the review may need what a
        # comment says in place); nothing that changes the host is.
        allowed_tools=f"{REVIEW_TOOLS} {forge_read_tools(forge)}" if forge else REVIEW_TOOLS,
        log=log,
        journal=journal,
        transcript=transcript,
        record_for=record_for,
        runtime=runtime,
        role=role,
    )

    def run_review(
        *,
        cwd: Path,
        context: str = "",
        resume_session: str = "",
        on_session: Callable[[str], None] | None = None,
        on_result: AgentCallback | None = None,
    ) -> str:
        # `context` is the runner's word on this branch — e.g. that it was
        # moved onto a predecessor that changed — ahead of the standing prompt.
        prompt = REVIEW_PROMPT + review_changelog_paragraph(cwd, repo)
        # Its own model, not the implementation one a build call names.
        return inner(
            f"{context}\n\n{prompt}" if context else prompt,
            cwd=cwd,
            model=model or models().review,
            resume_session=resume_session,
            on_session=on_session,
            on_result=on_result,
        )

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
    *,
    unit_id: str = "",
    run: Run | None = None,
    fix: Callable[..., str] | None = None,
    adopted_from: str = "",
    gate: Callable[[Path], str] | None = None,
    repo: RepoConfig | None = None,
    base: str = "",
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

    One `fix` serves every commit a unit makes — tests, implementation, each
    rework and a restack's adapt step — so the build run's agent fixes every
    rejection, reworks included. The fix rounds do not ask the usage guard:
    it decides whether a unit starts, and these are at most
    `COMMIT_FIX_ROUNDS` short runs per commit of a unit already under way.

    `adopted_from` names the chat session a commit made from a chat comes from, in a
    trailer beside the unit's.

    `gate` is a check run on the staged tree before the commit, for a checkout with no
    hooks of its own: it returns what it rejected, or nothing. Its output is handled as
    a rejected commit's is.
    """
    run = run or _run

    default_base = base

    def commit(message: str, *, cwd: Path, base: str = "") -> int:
        # The unit id in the trailer keeps a branch's history readable without
        # the planning repo open beside it.
        trailers = ([f"Unit: {unit_id}"] if unit_id else []) + (
            [f"Adopted-From: {adopted_from}"] if adopted_from else []
        )
        body = f"{message}\n\n" + "\n".join(trailers) + "\n" if trailers else message

        def attempt() -> subprocess.CompletedProcess | None:
            restore_unchanged_locks(repo, cwd, base or default_base)
            run(["git", "add", "-A"], cwd=cwd)
            unstage_untracked_locks(repo, cwd)
            unstage_artifacts(repo, cwd)
            if not run(["git", "diff", "--cached", "--quiet"], cwd=cwd).returncode:
                return None  # Nothing staged: an empty commit would be a lie.
            if gate is not None and (rejected := gate(cwd)):
                return subprocess.CompletedProcess(["gate"], 1, stdout=rejected, stderr="")
            return run(["git", "commit", "-q", "-m", body], cwd=cwd)

        def head() -> str:
            return run(["git", "rev-parse", "HEAD"], cwd=cwd).stdout.strip()

        result = attempt()
        # Once as is: a gate that rewrote the files has already fixed them.
        if result is not None and result.returncode:
            result = attempt()
        for _ in range(COMMIT_FIX_ROUNDS if fix is not None else 0):
            if fix is None or result is None or not result.returncode:
                break
            output = f"{result.stdout}\n{result.stderr}".strip()
            before = head()
            fix(COMMIT_FIX_PROMPT.format(output=output), cwd=cwd, model=models().implement)
            # The agent has `git` and could commit around the gate — a skip
            # flag, SKIP, another hooks path, a deleted hook. The policy hook
            # refuses the ones it can name; this catches every form, since
            # otherwise the next attempt finds nothing staged and reports it
            # as nothing to commit.
            if head() != before:
                raise CommitRejected(
                    f"the fix round committed on its own in {cwd} instead of leaving the "
                    f"commit to the pipeline, so the gate cannot be shown to have passed. "
                    f"The gate had said:\n{output}"
                )
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


def branch_commits(repo: Path, base: str) -> int:
    """How many commits the branch carries beyond its base.

    The question a resumed unit asks: not "did this run write anything" but
    "is the work there". A git failure raises rather than counting as none:
    "no commits of its own" can end a unit as satisfied, so an unresolvable
    base must not read as that.
    """
    return int(git_out(repo, "rev-list", "--count", f"{base}..HEAD"))


def _changed_files(repo: Path, base: str) -> list[str]:
    result = git(repo, "diff", "--name-only", f"{base}...HEAD", check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


def build_tier1(
    *,
    run: Run | None = None,
    changed: Callable[..., list[str]] | None = None,
    profile: ToolchainProfile | None = None,
    root_extras: list[str] | None = None,
    projects: list[ProjectConfig] | None = None,
    log: Callable[[str], None] | None = None,
    repo: RepoConfig | None = None,
) -> Callable[..., tuple[bool, str]]:
    """Lint the unit's own diff, then test the members it reaches.

    Each command it runs is logged with where it ran and how it ended, so a
    pass can be checked against CI afterwards: a tier 1 that passed on a branch
    CI then failed is only explicable from what it actually ran.

    Everything CI will run anyway, run locally first so a failure costs
    seconds rather than a push, a CI round trip and a red PR.

    **Scoped to the unit, not the repo.** Linting every file fails a unit for
    problems in files it never touched: the pilot's first unit died on a
    pre-existing type error elsewhere while its own three files were clean.
    The profile's lint command takes the base ref for that reason.

    **Scoped to the project, not the checkout.** A repo's projects need not sit
    at its root - a Python service two directories down, a web app below that -
    and a toolchain command run at the root of such a repo finds no project at
    all: the profile's check command there cannot even resolve its hooks, so a unit
    dies on tooling rather than on its own work. Each project's checks run
    inside it, under its own profile, and a file belongs to the deepest project
    that holds it. A file under no project is judged by the declared projects'
    own lint, which sees the whole diff. A repo declaring no projects is
    checked at its root under the repo's profile, exactly as before.

    **`whole_repo` switches to judging the tip instead of the diff.** A unit
    that produced no commits of its own has no diff to scope to: the diff-
    scoped lint command runs over an empty range and the diff-scoped test
    commands touch nothing, so both pass without checking anything at all.
    Judging such a unit "satisfied" on that basis would let any run that wrote
    nothing through. `whole_repo` runs the profile's whole-repo lint and every
    testable member's tests (plus the root `tests/`) instead, so the checks
    that make a unit satisfied are the repo's real tier 1, not an empty scope.
    """
    run = run or _run_limited
    changed = changed or _changed_files
    profile = profile or profiles.get("python-uv")

    def tier1(*, cwd: Path, base: str, whole_repo: bool = False) -> tuple[bool, str]:
        """(passed, what failed) — the output is what makes a retry useful."""
        extra = profile.extra_checks(repo) if repo is not None else []
        for where, toolchain, files in _work(cwd, base, whole_repo, projects, profile, changed):
            if whole_repo:
                lint_command = toolchain.lint_command_all_files()
                test_commands = toolchain.test_commands_all(where, root_extras=root_extras or [])
            else:
                lint_command = toolchain.lint_command(base)
                test_commands = toolchain.test_commands(where, files, root_extras=root_extras or [])

            for command in [lint_command, *test_commands]:
                result = ran(command, where, toolchain)
                if not toolchain.tolerates_exit(command, result.returncode):
                    isolate(command, result, where, toolchain)
                    return False, _failure(command, result)
        # Once per checkout, in its root: these look at the repo, not at a project.
        for command in extra:
            result = ran(command, cwd, profile)
            if not profile.tolerates_exit(command, result.returncode):
                return False, _failure(command, result)
        return True, ""

    def isolate(
        command: list[str],
        result: subprocess.CompletedProcess,
        where: Path,
        toolchain: ToolchainProfile,
    ) -> None:
        """Run the failed tests again, alone and serially, twice. Raises `FlakeFound` when
        they pass both times; returns when any fails again, or the profile cannot say
        which tests failed, so the failure stands."""
        failed_tests = getattr(toolchain, "failed_tests", None)
        rerun_command = getattr(toolchain, "serial_rerun_command", None)
        if failed_tests is None or rerun_command is None:
            return
        output = f"{result.stdout}\n{result.stderr}".strip()
        tests = failed_tests(output)
        if not tests:
            return
        rerun = rerun_command(command, tests)
        for _ in range(FLAKE_RERUNS):
            again = ran(rerun, where, toolchain)
            if not toolchain.tolerates_exit(rerun, again.returncode):
                return
        at = datetime.now(UTC)
        raise FlakeFound(
            tuple(
                Flake(
                    test=test,
                    command=shlex.join(command),
                    output=output[-4000:],
                    at=at,
                    directory=str(where),
                )
                for test in tests
            )
        )

    def ran(
        command: list[str], where: Path, toolchain: ToolchainProfile
    ) -> subprocess.CompletedProcess:
        started = time.monotonic()
        mark = spans.Mark()
        outcome = "error"
        try:
            result = run(command, cwd=where)
            ok = toolchain.tolerates_exit(command, result.returncode)
            outcome = "ok" if ok else f"exit {result.returncode}"
        finally:
            unit, change, node, round_number = spans.current_unit.get()
            spans.record_span(
                mark,
                log or (lambda message: None),
                unit=unit,
                change=change,
                node=node,
                round_number=round_number,
                outcome=outcome,
                command=" ".join(command),
            )
        if log is not None:
            passed = "passed" if ok else f"exit {result.returncode}"
            seconds = time.monotonic() - started
            log(f"  tier 1: {' '.join(command)} (in {where}) {passed}, {seconds:.0f}s")
        return result

    return tier1


def build_on_flake(
    store: UnitStore, installation: Installation, *, log: Callable[[str], None] = print
) -> Callable[[Unit, Flake], str | None]:
    """Make the unit wait on the one change that fixes a flake it met, and record it.
    Returns that change, or None for a unit of the change itself, which has nothing to
    wait on."""

    def on_flake(unit: Unit, flake: Flake) -> str | None:
        met = flake.model_copy(update={"unit": unit.id})
        fix = wait_on_fix(installation, met, store.get(unit.id))
        flake_record(installation).append(met.model_copy(update={"change": fix or ""}))
        log(f"{unit.id}: flaky test {flake.test} — " + (f"waits for {fix}" if fix else "no wait"))
        return fix

    return on_flake


def _failure(command: list[str], result: subprocess.CompletedProcess) -> str:
    """The command that failed, then the tail of what it printed: a bare
    "tier 1 failed" says nothing about which check or why."""
    printed = f"{result.stdout}\n{result.stderr}".strip()[-4000:]
    return f"$ {shlex.join(command)} (exit {result.returncode})\n{printed}".strip()


def _work(
    cwd: Path,
    base: str,
    whole_repo: bool,
    projects: list[ProjectConfig] | None,
    profile: ToolchainProfile,
    changed: Callable[..., list[str]],
) -> list[tuple[Path, ToolchainProfile, list[str]]]:
    """Where to run tier 1, under which toolchain, over which files.

    One entry per project the unit touched, its files relative to that project
    - a profile's test commands name paths from the directory they run in.
    A repo with no projects declared is one entry at its root, which is what
    every installation written before projects existed still gets.
    """
    if not projects:
        return [(cwd, profile, [] if whole_repo else changed(cwd, base))]
    if whole_repo:
        return [(cwd / p.path, profiles.get(p.profile), []) for p in projects]

    # Deepest first, so the web app claims its own files rather than the
    # service it sits inside.
    ordered = sorted(projects, key=lambda p: len(Path(p.path).parts), reverse=True)
    owned: dict[str, tuple[ProjectConfig, list[str]]] = {}
    for name in changed(cwd, base):
        for project in ordered:
            prefix = "" if project.path in (".", "") else f"{project.path}/"
            if not prefix or name.startswith(prefix):
                entry = owned.setdefault(project.path, (project, []))
                entry[1].append(name[len(prefix) :])
                break

    work = [
        (cwd / project.path, profiles.get(project.profile), files)
        for project, files in owned.values()
    ]
    # Never the repo root. A repo that declares its projects is saying its root
    # is not one of them, and a linter run there finds no config and fails
    # outright: a unit whose only mistake was updating docs that live above the
    # project stopped on exactly that. A lint command takes a ref range, not a
    # list of paths, so each project's own run already sees every file in the
    # diff, outside files included — there is nothing for a root run to add.
    #
    # A diff that no project owns (nothing but a README, or nothing at all) must
    # still not pass with nothing run, so the declared toolchains run over it:
    # that is where the hooks that would judge those files actually live.
    if not work:
        work = [(cwd / p.path, profiles.get(p.profile), []) for p in projects]
    return work


def _default_push(repo: Path, branch: str, last_pushed: str | None) -> str:
    return push_with_lease(repo, branch, last_pushed=last_pushed)


def build_push(
    store: UnitStore,
    *,
    push: Callable[..., str] | None = None,
    remote_head_of: Callable[[Path, str], str | None] | None = None,
    adopt: Callable[..., str] | None = None,
) -> Callable[..., str]:
    """Push a unit's branch with the lease its own history justifies.

    The lease names the SHA *this* runner last published, which the store has
    to remember because every tick is a separate process. Recording the new
    one afterwards is what makes the next restack's push safe.

    Every push passes here, so this is where a branch the host moved is
    caught — whichever unit it is, and whether or not a run of it moved it.
    After a stack merge the host rebases every PR above the merged one, not
    only the one sitting on it. Its head is adopted rather than overwritten,
    the old approval dropped, and `HostMoved` raised so review sees it first.
    A host head holding the same change (same diff id over the trunk) only moves
    the lease: the approval stands and the approved head is pushed.
    """
    push = push or _default_push
    remote_head_of = remote_head_of or remote_head
    adopt_head = adopt or adopt_host_head

    def do_push(branch: str, *, cwd: Path) -> str:
        unit_id = branch.removeprefix(active().git.branch_prefix)
        try:
            last_pushed = store.get(unit_id).pushed
        except KeyError:
            last_pushed = None

        remote = remote_head_of(cwd, branch) if last_pushed else ""
        here = git(cwd, "rev-parse", "--verify", "-q", branch, check=False).stdout.strip()
        if remote and remote != last_pushed and here == remote:
            # Not moved by anyone: a push of ours whose recording was lost.
            store.record_push(unit_id, remote)
            last_pushed = remote
        elif remote and last_pushed and remote != last_pushed:
            adopt_head(
                cwd,
                branch,
                host_head=remote,
                last_pushed=last_pushed,
                cwd=cwd,
                base=local_ref(trunk_of(store.get(unit_id).repo), repo=store.get(unit_id).repo),
            )
            store.record_push(unit_id, remote)
            after = git(cwd, "rev-parse", "--verify", "-q", branch, check=False).stdout.strip()
            if here and after == here:
                # The host holds the same change, so what review approved
                # stands: only the lease moves, and the approved head is pushed.
                last_pushed = remote
            else:
                store.record_approval(unit_id, "")
                raise HostMoved(
                    f"the host moved {branch} from {last_pushed[:9]} to {remote[:9]}; "
                    "adopted its head, which review has not seen"
                )

        sha = push(cwd, branch, last_pushed)
        try:
            store.record_push(unit_id, sha)
        except KeyError:
            pass  # A branch with no unit behind it: nothing to lease against.
        return sha

    return do_push


def build_post_status(
    *, for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None, head: str = ""
) -> Callable[[str, Tier2Result], None]:
    """Post a tier 2 result as a commit status on whichever host the repo lives on.

    `head` is the branch it belongs to, for a host that also shows it on the
    open pull request."""
    for_repo = for_repo or forges.for_repo

    def post(repo_name: str, result: Tier2Result) -> None:
        forge, repo = for_repo(repo_name)
        tier2_post_status(forge, repo, result, head=head)

    return post


class _StackingHost(RegistersStacks, Protocol):
    """What the PR step needs of a host: opening a PR, and stacking it."""

    def find_pr(self, repo: RepoId, *, head: str) -> int | None: ...

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int: ...

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None: ...

    def pr_changes(self, repo: RepoId, pr: int) -> list[FileChange]: ...


# How long to wait before asking a stack busy with another request again, once
# per retry; after the last the refusal is recorded. Overlapping ticks make a
# busy stack ordinary, not persistent, but not gone the instant it is asked.
STACK_BACKOFF: tuple[float, ...] = (1.0, 2.0)


def build_open_pr(
    *,
    for_repo: Callable[[str], tuple[_StackingHost, RepoId]] | None = None,
    store: UnitStore | None = None,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[..., int]:
    """Create the unit's PR, or update the one it already has.

    Every restack pushes the branch again, so this runs repeatedly for one
    unit. A second create would fail outright, and the body would then never
    reflect the restack. Which host the PR is opened on is the forge's
    business; this only knows that a unit has one.

    Once the PR exists, and where the host has stacks, it is registered in the
    stack of the PR beneath it. Advisory: a refusal is recorded on the unit and
    logged once, and changes nothing else.

    Two bodies, because only this step knows which one is true: `body` for a
    PR the host shows in no stack, which has to state the order itself, and
    `stacked_body` for one it does. The PR goes up with the one its record
    predicts, and is corrected at once if registering says otherwise.
    """
    for_repo = for_repo or forges.for_repo

    def open_pr(
        unit: Unit, *, body: str, base: str, cwd: Path, stacked_body: str | None = None
    ) -> int:
        forge, repo = for_repo(unit.repo)
        branch = branch_name(unit)
        number = forge.find_pr(repo, head=branch)

        stacking = store is not None and forge.supports_stacks
        below = _below(unit, base) if stacking else None
        expected = stacked_body is not None and below is not None and not _recorded_refusal(unit)
        chosen = stacked_body if expected and stacked_body is not None else body

        if number is None:
            number = forge.create_pr(
                repo, head=branch, base=base, title=f"{unit.id}: {unit.title}", body=chosen
            )
            fresh = True
        else:
            forge.update_pr(repo, number, base=base, body=chosen)
            fresh = False

        if stacking:
            stacked = _register_stack(forge, repo, unit, number, below=below, fresh=fresh)
            if stacked_body is not None and stacked != expected:
                # A PR the host would not stack must still say what order it
                # merges in, and one it did stack no longer should.
                forge.update_pr(repo, number, base=base, body=stacked_body if stacked else body)
        try:
            _record_size(unit, forge.pr_changes(repo, number))
        except Exception as error:
            log(f"{unit.id}: could not read the size of PR #{number}: {error}")
        return number

    def _record_size(unit: Unit, changes: list[FileChange]) -> None:
        """Record the size the reviewer sees now, and say so when it is over
        the ceiling. Bookkeeping: the caller never lets it stop the unit."""
        if not changes:
            return
        lines = actual_lines(changes)
        if store is not None:
            store.set_actual_lines(unit.id, lines)
        if over_ceiling(lines):
            log(
                f"{unit.id}: estimated {unit.estimated_lines}, landed {lines}, "
                f"over the ceiling of {active().limits.max_unit_lines}"
            )

    def _below(unit: Unit, base: str) -> int | None:
        """The PR the base branch belongs to: found by what the PR targets, not
        by a direct dependency, since the base may be reached through a
        satisfied one."""
        assert store is not None
        return next(
            (
                dep.pr
                for dep in store.all()
                if dep.id != unit.id and dep.repo == unit.repo and dep.branch == base and dep.pr
            ),
            None,
        )

    def _recorded_refusal(unit: Unit) -> str:
        assert store is not None
        try:
            return store.get(unit.id).stack_refusal
        except KeyError:
            return ""

    def _register_stack(
        forge: _StackingHost,
        repo: RepoId,
        unit: Unit,
        number: int,
        *,
        below: int | None,
        fresh: bool,
    ) -> bool:
        """Whether the PR is now in a host stack."""
        assert store is not None
        stacked = False
        refusal = ""
        # On the trunk, nothing is beneath it: a stack of one is not a stack.
        # A refusal from when it had a base is no longer anyone's concern.
        delays = iter(STACK_BACKOFF)
        while below is not None:
            try:
                # Asked of the host, not remembered: a person may have merged
                # or restructured the stack since. A PR just created is in none.
                if not fresh and forge.stack_of(repo, number) is not None:
                    stacked, refusal = True, ""
                    break
                stack = forge.stack_of(repo, below)
                if stack is not None and stack.open:
                    forge.add_to_stack(repo, stack.number, [number])
                else:
                    # In no stack, or in one whose PRs have all merged, which
                    # cannot be extended: start a new one, bottom first.
                    forge.create_stack(repo, [below, number])
                stacked, refusal = True, ""
                break
            except StackRefused as refused:
                refusal = refused.reason
                delay = next(delays, None) if refused.concurrent else None
                if delay is None:
                    break
                sleep(delay)
            except Exception as error:  # noqa: BLE001
                # Anything else the host or the network throws is a refusal
                # too: the PR is open, and registering is advisory.
                refusal = f"{type(error).__name__}: {error}"
                break

        recorded = _recorded_refusal(unit)
        if refusal and refusal != recorded:
            log(f"{unit.id}: #{number} not registered in a stack: {refusal}")
        if refusal != recorded:
            store.set_stack_refusal(unit.id, refusal)
        return stacked

    return open_pr


def build_fetch(
    checkouts: Mapping[str, Path], *, turn: Callable[[str], AbstractContextManager[object]]
) -> Callable[[Unit], None]:
    """Fetch one unit's repo, in that repo's turn. Raises when the fetch fails."""

    def fetch(unit: Unit) -> None:
        if not has_origin(checkouts[unit.repo]):
            return  # no remote: the repo's own trunk and branches are current
        with turn(unit.repo):
            result = git(checkouts[unit.repo], "fetch", "-q", "--prune", "origin", check=False)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"git fetch exited {result.returncode}")

    return fetch


def build_fresh_base(
    store: UnitStore,
    *,
    for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None,
    record_merge: Callable[[str, int], object],
) -> Callable[[Unit, str], str]:
    """A unit's base as the forge has it, recording a merge the store missed.

    `record_merge` is given the repo and the pull request number: a number
    names a unit only together with its repo.

    The parent's state comes from the forge's listing, not a lookup of the one
    pull request: no forge method answers a single pull request's state, and
    adding one for this is not worth it. A parent that has dropped off the
    listing's newest 100 goes unseen, which leaves the unit on the base it has
    - the behaviour before this check - and a base the host has deleted is
    caught again when the pull request opens.
    """

    for_repo = for_repo or forges.for_repo

    def fresh_base(unit: Unit, base: str) -> str:
        parent = next(
            (
                other
                for other in store.all()
                if other.state == IN_REVIEW and other.pr and branch_name(other) == base
            ),
            None,
        )
        if parent is None or parent.pr is None:
            return base
        forge, repo = for_repo(unit.repo)
        merged = any(
            pull.number == parent.pr and pull.state == MERGED
            for pull in forge.list_prs(repo, head_prefix=base)
        )
        if not merged:
            return base
        record_merge(unit.repo, parent.pr)
        return base_of(unit, store.all())

    return fresh_base


def build_release_dependents(
    store: UnitStore, installation: Installation, *, log: Callable[[str], None] = print
) -> Callable[[Unit], list[str]]:
    """Move what is stacked on a unit that has become satisfied onto its new
    base, as `events.on_merged` does for a merged one, with the same moves the
    merge handler is built with. Returns what it could not move, one line each.

    The unit's own worktree and branch are left alone: the run that found it
    satisfied is still standing in that tree. See `build_remove_satisfied`.
    """
    # Late: the cli package and `events` import this module.
    from agent_build_kit.cli.pipeline import build_stack_moves
    from agent_build_kit.pipeline import events

    moves = build_stack_moves(store, installation)

    def release(unit: Unit) -> list[str]:
        return events.release_children(
            store.get(unit.id),
            store=store,
            restack=moves["restack"],
            claim=moves["claim"],
            retarget=moves["retarget"],
            rebase_cap=moves["rebase_cap"],
            resume=moves["resume"],
            settled=events.build_settled(installation.checkouts),
            log=log,
        )

    return release


def build_remove_satisfied(
    store: UnitStore, installation: Installation, *, log: Callable[[str], None] = print
) -> Callable[[Unit], None]:
    """Remove a satisfied unit's worktree and branch, for the run to call once
    it has left the tree. See `events.remove_satisfied`."""
    # Late: the cli package and `events` import this module.
    from agent_build_kit.cli.pipeline import build_stack_moves
    from agent_build_kit.pipeline import events

    moves = build_stack_moves(store, installation)

    def remove(unit: Unit) -> None:
        events.remove_satisfied(
            store.get(unit.id),
            store=store,
            claim=moves["claim"],
            remove_worktree=moves["remove_worktree"],
            delete_branch=moves["delete_branch"],
            on_new_base=lambda child: events.pr_based_on(child, base_of(child, store.all())),
            log=log,
        )

    return remove


def build_close_pr(
    *, for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None
) -> Callable[[Unit, int, str], None]:
    """Post the reason a satisfied unit's stale pull request is closing, then
    close it — in that order, so the explanation is never missing.

    Marked, like every other pipeline post, so `events.review_lines` and
    `_latest_comment` leave it out: an unmarked reason that outlives a failed
    close would come back on the next poll as a reviewer's "new comment" and
    send the unit to rework over its own explanation.

    A post that fails is not followed by a close: `post_comment` returns `[]`
    when the host call failed (both `GitHubForge` and the Azure forge do
    this), and closing anyway would leave the PR shut with no reason on it —
    the one outcome the ordering here exists to prevent.
    """
    for_repo = for_repo or forges.for_repo

    def close_pr(unit: Unit, pr: int, reason: str) -> None:
        forge, repo = for_repo(unit.repo)
        body = f"{reason}\n{MARKER}"
        # A repeat of this pair finds the reason already there and does not post it again.
        posted = forge.comment_exists(repo, pr, MARKER, body) or forge.post_comment(
            repo, pr, body=body
        )
        if not posted:
            raise RuntimeError(f"reason not posted on #{pr}; left open")
        forge.close_pr(repo, pr)

    return close_pr


def build_worktree(
    repos: dict[str, Path],
    *,
    root: Path,
    prepare: Callable[..., Path] | None = None,
    repo: RepoConfig | None = None,
) -> Worktree:
    """Give a unit its own checkout of the repo it lands in.

    Units run in parallel and land in different repos, so a shared checkout
    would put two agents in one working tree. A repo we have no checkout of is
    refused here rather than three steps later, with a worktree half built.
    """
    prepare = prepare or (
        lambda repo, branch, base, tree_root, **options: prepare_worktree(
            repo, branch, base=base, root=tree_root, **options
        )
    )

    def worktree(unit: Unit, base: str, allow_dirty: bool = False) -> Path:
        if unit.repo not in repos:
            raise KeyError(
                f"{unit.id} targets {unit.repo}, which has no checkout configured "
                f"(known: {', '.join(sorted(repos)) or 'none'})"
            )
        options: dict[str, Any] = {"allow_dirty": True} if allow_dirty else {}
        if locks := lock_paths(repo):
            options["locks"] = locks
        if artifacts := artifact_patterns(repo):
            options["artifacts"] = artifacts
        return prepare(repos[unit.repo], branch_name(unit), base, root, **options)

    return worktree


Reading = Callable[[], UsageReading | None]
Decide = Callable[[UsageReading | None], Decision]


def _guard_decision(
    usage: Reading | None, decide: Decide | None, start: Callable[[], Decision] | None
) -> Callable[[], tuple[Decision, datetime | None]]:
    """One decision of the usage guard, and the reset time to fall back on when a refusal
    names no time of its own.

    By default the decision is `decide_start`'s, which asks the endpoint only when a fresh
    reading could change it; the reset is the one the decision carries. A caller with its
    own `start`, or its own `usage` and `decide`, is asked as it says.
    """
    if start is None and usage is None and decide is None:
        start = decide_start
    if start is not None:
        decide_now = start

        def decided() -> tuple[Decision, datetime | None]:
            decision = decide_now()
            return decision, decision.resets_at

        return decided

    read = usage or current_usage
    judge = decide or may_start_unit

    def judged() -> tuple[Decision, datetime | None]:
        reading = read()
        return judge(reading), reading.resets_at if reading else None

    return judged


def _when(decision: Decision, reset: datetime | None) -> datetime | None:
    if not decision.may_start and decision.resume_at:
        return decision.resume_at
    return reset


def build_may_start(
    *, usage: Reading | None = None, start: Callable[[], Decision] | None = None
) -> Callable[[], tuple[bool, str]]:
    """The usage guard, in the shape the runner asks for.

    Checked again per unit rather than once per tick: a tick can start several
    units, and the window moves while they run.
    """
    decided = _guard_decision(usage, None, start)

    def may_start() -> tuple[bool, str]:
        # No window to read for a runtime that has none; its own rate-limit
        # refusal is what stops it.
        runtime = runtimes.active()
        if not runtime.supports_usage_tracking:
            return True, f"runtime {runtime.name} has no usage window"
        decision, _ = decided()
        return decision.may_start, decision.reason

    return may_start


def build_resume_at(
    *,
    usage: Reading | None = None,
    decide: Decide | None = None,
    start: Callable[[], Decision] | None = None,
) -> Callable[[], datetime | None]:
    """When the usage guard expects to allow a start again, in the shape the
    runner asks for: the guard's own answer, which counts the ramp towards the
    window's reset, and the reset itself when it has none."""
    decided = _guard_decision(usage, decide, start)

    def resume_at() -> datetime | None:
        return _when(*decided())

    return resume_at


def build_usage_gate(
    *,
    usage: Reading | None = None,
    decide: Decide | None = None,
    start: Callable[[], Decision] | None = None,
) -> tuple[Callable[[], tuple[bool, str]], Callable[[], datetime | None]]:
    """`may_start` and `resume_at` for one gate, taking one decision between them.

    A gate asks whether a start is allowed and, when it is not, when to look
    again. Both answers come from the decision the first took, so a refusal is
    one decision of the guard and its reason and its deadline describe the same moment.
    """
    decided = _guard_decision(usage, decide, start)
    held: list[tuple[Decision, datetime | None]] = []

    def may_start() -> tuple[bool, str]:
        runtime = runtimes.active()
        if not runtime.supports_usage_tracking:
            held.clear()
            return True, f"runtime {runtime.name} has no usage window"
        held[:] = [decided()]
        return held[0][0].may_start, held[0][0].reason

    def resume_at() -> datetime | None:
        return _when(*(held[0] if held else decided()))

    return may_start, resume_at


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
        env: Mapping[str, str] | None = None,
        projects: list[ProjectConfig] | None = None,
    ) -> None:
        self.unit = unit
        self._projects = projects or []
        # `verify.env`: what the live-stack tests need, the same here as after
        # a merge. Without it a unit's tier 2 ran them with none of it, and a
        # test needing it failed at setup however the unit was built.
        self._test_env = {"env": {**os.environ, **env}} if env else {}
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
        self._status = status or build_post_status(head=branch_name(unit))
        self._timeout = timeout
        self.result: Tier2Result | None = None

    def run(self, *, cwd: Path) -> tuple[bool, str]:
        if self._dev_stack is not None and (cwd / self._dev_stack).is_file():
            return self._run_on_dev_stack(cwd, self._dev_stack)
        # The same entries tier 1 resolves, over the whole repo: tier 2 has no
        # changed files to narrow to, and a project's `testpaths` decide what
        # pytest collects only when it runs from that project's directory.
        entries = [
            (where, toolchain, toolchain.tier2_commands(where, marker=self._marker))
            for where, toolchain, _ in _work(
                cwd, "", True, self._projects, self._profile, lambda *_: []
            )
        ]
        sha = self._sha(cwd)
        passed = failed = skipped = 0
        duration = 0.0
        outputs: list[str] = []

        # A queue, not a fail-fast lock: a second unit's tier 2 tests are
        # perfectly valid, there is simply one local stack to run them on.
        with stack_lock(self.lock, self._timeout):
            for where, toolchain, commands in entries:
                # A project's output is labelled with it; a repo with no
                # projects has nothing to say about where.
                label = f" (in {where.relative_to(cwd)})" if where != cwd else ""
                for command in commands:
                    completed = self._run(command, cwd=where, **self._test_env)
                    out = f"{completed.stdout or ''}{completed.stderr or ''}"
                    p, f, s, d = toolchain.parse_test_summary(out)
                    # A zero exit code with no counts parsed is still a pass, and so
                    # is "no tests collected" — a member with no live-stack tests. Any
                    # other non-zero exit is a failure even if no summary printed.
                    nothing = toolchain.no_tests_collected_exit
                    if completed.returncode not in (0, nothing) and not f:
                        f = 1
                    passed, failed, skipped, duration = (
                        passed + p,
                        failed + f,
                        skipped + s,
                        duration + d,
                    )
                    if f or completed.returncode not in (0, nothing):
                        outputs.append(f"$ {' '.join(command)}{label}\n{out}")
                    elif p:
                        outputs.append(f"$ {' '.join(command)}{label}\n{out[-1500:]}")

        output = "\n\n".join(outputs)
        command = " && ".join(
            " ".join(c) + (f" (in {where.relative_to(cwd)})" if where != cwd else "")
            for where, _, commands in entries
            for c in commands
        )

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
                            completed, command = self._run(test, cwd=cwd, **self._test_env), test
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


def head_reachable(cwd: Path, head: str) -> bool:
    """Whether the worktree can still read the commit `head`, which a rewrite may have left to
    be collected."""
    return not git(cwd, "cat-file", "-e", f"{head}^{{commit}}", check=False).returncode


def _head_sha(cwd: Path) -> str:
    return git(cwd, "rev-parse", "HEAD", check=False).stdout.strip()


def is_linear(cwd: Path, base: str) -> bool:
    """Whether the tree's HEAD still sits on `base`: its tip is an ancestor.

    Only a definite "no" (exit 1) is not linear. Any other failure — a base
    that cannot be resolved here — is unknown, and not worth a false alarm.
    """
    return git(cwd, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode != 1


def _stack_versions(command: list[str] | None, *, run: Run | None = None) -> dict[str, str]:
    """What the live stack was when tier 2 ran, so the claim can be checked:
    `verify.stack_versions_command`'s output, one `name<TAB>image` per line.
    None records nothing."""
    if not command:
        return {}
    try:
        result = (run or _run)(list(command))
    except (FileNotFoundError, PermissionError) as error:
        logger.warning("stack versions not recorded: %s could not start: %s", command[0], error)
        return {}
    versions: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, image = line.partition("\t")
        if name and image:
            versions[name.strip()] = image.strip()
    return versions


def own_work_starts_after(tree: Path, base: str, unit: Unit, store: UnitStore) -> str:
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
    known = list(store.all())
    index = {u.id: u for u in known}
    for dep in through_satisfied(unit, known):
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


def _move_without_resolver(
    repo: Path, branch: str, *, new_base: str, old_base: str, **_intent: str
) -> Moved:
    """`move_branch_onto` with no resolver: a conflict is aborted and raised."""
    return move_branch_onto(repo, branch, new_base=new_base, old_base=old_base)


def build_restack_onto(
    store: UnitStore, *, move: Callable[..., Moved] | None = None, repo: RepoConfig | None = None
):
    """Move a resuming unit's branch onto its base, if the base has moved.

    Reuses `move_branch_onto` — the primitive, with its LLM conflict resolution
    and its check that the resolution did not simply delete one side — rather
    than `events.build_restack`, which also pushes, retargets the PR and
    comments. A resuming unit is not ready to push: it still has a review loop
    and tier 1 ahead of it.

    "Has the base moved" is whether the base's tip is still an ancestor of this
    branch. If it is, nothing to do — and a rebase would be actively harmful,
    since it rewrites every commit and invalidates any check already run.

    `resolve=False` moves without the conflict resolver, for the check before a
    push: a conflict is aborted, the branch left at its head, and reported as
    `Restacked.conflict`, so the unit is held and the resolution happens at the
    start of its next run, under the usage gate and with review told of it.
    """
    resolving = move or partial(resolved_move, repo_config=repo)

    def restack_onto(
        *, tree: Path, branch: str, base: str, unit: Unit, resolve: bool = True
    ) -> Restacked | None:
        move = resolving if resolve else _move_without_resolver
        if _is_ancestor(tree, base):
            return None

        old_base = own_work_starts_after(tree, base, unit, store)
        if not old_base:
            return None
        restore_unchanged_locks(repo, tree, base)

        # Named for the resolver and the reviewer: the predecessor that moved.
        onto = predecessor(unit, base, store)
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
                old_tests=tuple(defined_tests_in_range(tree, old_base, old_head)),
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


def predecessor(unit: Unit, base: str, store: UnitStore) -> StoredUnit | None:
    """The unit this one is built on: the base's own unit, or — when the base
    is the trunk because the parent merged — the same-repo parent it depends on."""
    units = store.all()
    by_branch = next((u for u in units if u.branch and u.branch == base), None)
    if by_branch is not None:
        return by_branch
    index = {u.id: u for u in units}
    parents = [
        index[d]
        for d in through_satisfied(unit, units)
        if d in index and index[d].repo == unit.repo
    ]
    return parents[-1] if parents else None


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def _test_spans(source: str) -> list[tuple[str, int, int]]:
    """Each `test_*` function's name and first and last line, decorators included."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        (
            node.name,
            min([d.lineno for d in node.decorator_list] + [node.lineno]),
            node.end_lineno or node.lineno,
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    ]


def _lines_in(spans: list[tuple[str, int, int]], first: int, count: int) -> set[str]:
    """Tests whose span holds any of `count` lines starting at `first`."""
    return {name for name, lo, hi in spans if count and first <= hi and first + count - 1 >= lo}


def defined_tests_in_range(tree: Path, old_base: str, old_head: str) -> list[str]:
    """Which tests the commit range `old_base..old_head` defined, deleted or edited inside.

    From which lines the range added or removed and which test each falls
    within, not from the diff's text: a test that only sits in the diff's
    context, beside an edit, is not the unit's.
    """
    names = git(
        tree, "diff", "-z", "--name-only", "--no-renames", old_base, old_head, "--", "*.py",
        check=False, errors="surrogateescape",
    ).stdout  # fmt: skip
    found: set[str] = set()
    for path in (p for p in names.split("\0") if p):
        diff = git(
            tree, "diff", "-U0", "--no-renames", old_base, old_head, "--", path,
            check=False, errors="replace",
        ).stdout  # fmt: skip
        old = git(tree, "show", f"{old_base}:{path}", check=False, errors="replace")
        new = git(tree, "show", f"{old_head}:{path}", check=False, errors="replace")
        old_spans = _test_spans(old.stdout) if old.returncode == 0 else []
        new_spans = _test_spans(new.stdout) if new.returncode == 0 else []
        for hunk in HUNK.finditer(diff):
            old_at, old_n, new_at, new_n = hunk.groups()
            found |= _lines_in(old_spans, int(old_at), int(old_n or 1))
            found |= _lines_in(new_spans, int(new_at), int(new_n or 1))
    return sorted(found)


def tests_in(tree: Path) -> set[str]:
    """Every test function in the worktree as it stands."""
    out = git(tree, "grep", "-hoE", "def test_[A-Za-z0-9_]+", "--", "*.py", check=False).stdout
    return {line.removeprefix("def ").strip() for line in out.splitlines() if line.strip()}


def _test_bodies(source: str) -> dict[str, list[str]]:
    """Each `test_*` function's own source text, by name, decorators included.

    Body against body, not the file's diff: a test moved or resurrounded by
    unrelated edits should not read as changed, but one whose assertions,
    markers or parametrized cases actually shifted must — even kept under its
    old name. Every same-named test is kept (in different classes, say), so a
    change to any of them shows. A test moved into a class reads as changed,
    the safe direction.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines()
    bodies: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test_"
        ):
            first = min([d.lineno for d in node.decorator_list] + [node.lineno])
            end = node.end_lineno or node.lineno
            bodies.setdefault(node.name, []).append("\n".join(lines[first - 1 : end]))
    return {name: sorted(texts) for name, texts in bodies.items()}


def tests_changed(tree: Path, ref: str) -> set[str]:
    """Test functions whose body differs between `ref` and the tree, per file.

    Compared file by file in both directions, so a test that only survived the
    replay by name — kept, but silently weakened — is caught, and so is one
    gone from the file it was in, even when the same name lives on in another
    file or in a string. A test moved to another file unchanged reads as
    changed. Data living outside the function, such as a module-level table a
    parametrize reads, is not seen.
    """
    # `-z` so git does not C-quote paths; no `check=False`, since a failing
    # listing must not read as "nothing changed".
    diff = git(
        tree,
        "diff",
        "-z",
        "--name-only",
        "--no-renames",
        ref,
        "--",
        "*.py",
        errors="surrogateescape",
    )
    new = git(
        tree,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        "*.py",
        errors="surrogateescape",
    )
    paths = {p for p in (diff.stdout + "\0" + new.stdout).split("\0") if p}
    changed: set[str] = set()
    for path in paths:
        file = tree / path
        current = _test_bodies(file.read_text(errors="replace")) if file.is_file() else {}
        old_source = git(tree, "show", f"{ref}:{path}", check=False, errors="replace")
        old = _test_bodies(old_source.stdout) if old_source.returncode == 0 else {}
        changed |= {n for n in old.keys() | current.keys() if old.get(n) != current.get(n)}
    return changed


def reset_to(tree: Path, onto: str, keep: str) -> None:
    """Keep the current work under `keep`, then put the branch on `onto`.

    A ref rather than a branch: it is there for the adapt step to read from,
    not to be built on or pushed, and a branch would clutter the checkout.
    """
    git(tree, "update-ref", keep, "HEAD")
    git(tree, "reset", "--hard", "-q", onto)


def _is_ancestor(tree: Path, base: str, of: str = "HEAD") -> bool:
    return not git(tree, "merge-base", "--is-ancestor", base, of, check=False).returncode


def build_upstream_incomplete(store: UnitStore) -> Callable[..., tuple[Cause, str] | None]:
    """Why a unit should stop, if something it is built on went back.

    Read from the store each time rather than captured once: the poller that
    requeues an upstream unit runs in a different process from the build that
    has to notice, and the store is the only thing they share.

    Only same-repo parents. A cross-repo dependency is an ordering constraint
    that is already satisfied by a merge, not a branch this unit sits on, so it
    cannot move underneath it.
    """

    def upstream_incomplete(unit: Unit) -> tuple[Cause, str] | None:
        known = list(store.all())
        index = {u.id: u for u in known}
        for dep in through_satisfied(unit, known):
            parent = index.get(dep)
            if parent and parent.repo == unit.repo and parent.state not in REVIEWED:
                return (
                    Cause.UPSTREAM_WENT_BACK,
                    f"{dep} is {parent.state} — it went back after this unit started",
                )
        return None

    return upstream_incomplete


def branch_is_changing(
    parent: StoredUnit, graph: list[StoredUnit], head: Callable[[StoredUnit], str]
) -> str:
    """Why a predecessor's branch is changing, or an empty string when it isn't.

    A predecessor in review, merged or satisfied is settled. Otherwise it is
    changing when its branch holds a commit beyond its last pushed head, when it
    is rebasing (its history is being rewritten before a new head exists), or
    when it is itself planned for a changing upstream or a moved base.
    """
    if parent.state in REVIEWED:
        return ""
    if parent.state == PLANNED and parent.cause is Cause.UPSTREAM_WENT_BACK:
        return "it is planned, waiting on a changing upstream"
    if parent.state == PLANNED and parent.cause is Cause.BASE_CHANGED:
        return "it is planned to move onto a moved base"
    if effective_state(parent, graph) == "rebasing":
        return "it is rebasing"
    now = head(parent)
    if now and now != parent.pushed:
        return "its branch holds a commit it has not pushed"
    return ""


def follow_predecessors(
    store: UnitStore,
    *,
    head: Callable[[StoredUnit], str],
    claim: Callable[[StoredUnit], AbstractContextManager[object]],
    log: Callable[[str], None] = print,
) -> list[str]:
    """Set each unit in review back to planned while a same-repo predecessor's
    branch is changing; returns the ids moved.

    `head` reads a unit's branch head ("" when it has none). `branch_is_changing`
    says when a branch is changing. Repeats until
    nothing moves, so a chain of dependents goes back in one pass. A unit with a
    deferred restack is skipped, and one whose branch is busy is left for the
    next pass.
    """
    moved: list[str] = []
    progressed = True
    while progressed:
        progressed = False
        graph = list(store.all())
        index = {u.id: u for u in graph}
        for unit in graph:
            if unit.state != IN_REVIEW or unit.cause in (
                Cause.RESTACK_DEFERRED,
                Cause.RESTACK_CONFLICT,
            ):
                continue
            found = None
            for dep in through_satisfied(unit, graph):
                parent = index.get(dep)
                if not parent or parent.repo != unit.repo:
                    continue
                if why := branch_is_changing(parent, graph, head):
                    found = (parent, why)
                    break
            if found is None:
                continue
            parent, why = found
            note = f"{parent.id} is changing: {why}"
            try:
                with claim(unit):
                    # A build may have taken the unit while the claim was waited for.
                    if store.get(unit.id).state != IN_REVIEW:
                        continue
                    store.set_state(unit.id, PLANNED, note=note, cause=Cause.UPSTREAM_WENT_BACK)
            except BranchBusy:
                continue
            log(f"{unit.id}: set back to planned — {note}")
            moved.append(unit.id)
            progressed = True
    return moved


def tip(tree: Path, ref: str) -> str:
    """The commit `ref` names in the worktree, or an empty string when it names none."""
    return git(tree, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False).stdout.strip()


def build_base_moved(store: UnitStore) -> Callable[..., tuple[Cause, str] | None]:
    """Why a unit's base is no longer the one its run started on, if it isn't.

    Two ways. A parent merging while its child builds: `events.on_merged` does
    not rebase a tree a build is using, so the build has to notice itself,
    from the store. And a parent restacked while its child builds — its own
    parent merged — keeps its name but not its commits: `start`, the base's
    tip when the run set up its worktree, is then no longer under the base. Either
    way the build stops before its next step. Pushing on regardless would open
    its PR carrying the parent's old commits.
    """

    def base_moved(unit: Unit, base: str, *, tree: Path, start: str) -> tuple[Cause, str] | None:
        now = base_of(unit, store.all())
        if now != base:
            return Cause.BASE_CHANGED, f"its base moved from {base} to {now} while it built"
        # Advanced is fine — a parent's rework adds on top, and the review or
        # the resume's restack takes it in. Rewritten is not.
        if start and not _is_ancestor(tree, start, local_ref(base, repo=unit.repo)):
            return Cause.BASE_CHANGED, f"its base {base} was rewritten while it built"
        return None

    return base_moved


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
    ref = local_ref(installation.repo(base).default_branch, repo=base)
    return lambda: prepare(
        installation.checkouts[base], "_dev_stack_base", ref=ref, root=installation.worktree_root
    )


def build_runner(
    unit: Unit,
    *,
    store: UnitStore,
    installation: Installation,
    record_merge: Callable[[str, int], object] = lambda repo, pr: None,
    log: Callable[[str], None] = print,
    log_reaches_run_log: bool = False,
    journal: Callable[[str], None] | None = None,
    transcript: Callable[[str], None] | None = None,
) -> UnitRunner:
    """Assemble the runner for one unit, with every step bound to reality.

    Per unit rather than once: the commit trailer, the tier 2 session and the
    status all belong to this unit and nothing else.
    """
    # Here and not at the top: `events` imports this module.
    from agent_build_kit.pipeline.events import build_fetch_comments  # noqa: PLC0415

    repo: RepoConfig = installation.repo(unit.repo)
    profile = profiles.get(repo.profile)
    root = installation.state_dir
    # One stamp for this thread's whole run: every call in it is one run to retention.
    record_for = (unit, transcript_dir(root), datetime.now(UTC))
    tier2 = Tier2Session(
        unit,
        lock=root / "tier2.lock",
        under=dev_stack_underneath(unit, installation),
        profile=profile,
        marker=repo.tests.tier2_marker,
        dev_stack=repo.dev_stack.script if repo.dev_stack else None,
        stack_versions_command=stack_versions_for(
            installation.config.verify, infra.get(repo.infra)
        ),
        env=installation.verify_env(),
        projects=repo.projects,
    )
    planning_repo = installation.root
    # Units build in parallel, and two in one repo share its `.git`. Adding a
    # worktree and pushing both take git's own locks there, which fail rather
    # than wait — so those two steps take turns per repo. Everything else
    # happens inside the unit's own worktree and needs no turn-taking.
    unit_repo_turn = partial(file_lock, root / "locks" / f"repo-{unit.repo}.lock")

    def repo_turn_of(name: str) -> AbstractContextManager[object]:
        return file_lock(root / "locks" / f"repo-{name}.lock")

    worktree = build_worktree(installation.checkouts, root=installation.worktree_root, repo=repo)
    push = build_push(store)

    def worktree_in_turn(unit: Unit, base: str) -> Path:
        with unit_repo_turn():
            return worktree(unit, base)

    def push_in_turn(branch: str, *, cwd: Path) -> str:
        with unit_repo_turn():
            return push(branch, cwd=cwd)

    forge = forges.get(repo.forge)
    tools = allowed_tools(profile, forge)
    run = build_run(
        planning_repo=planning_repo,
        allowed_tools=tools,
        log=log,
        journal=journal,
        transcript=transcript,
        record_for=record_for,
    )
    gate_may_start, gate_resume_at = build_usage_gate()
    return UnitRunner(
        store=store,
        leases=Leases(lease_dir(root)),
        planning_repo=planning_repo,
        repo_config=repo,
        worktree=worktree_in_turn,
        reset_to=reset_to,
        head_reachable=head_reachable,
        tests_in=tests_in,
        tests_changed=tests_changed,
        may_start=gate_may_start,
        resume_at=gate_resume_at,
        run=run,
        run_review=build_run_review(
            planning_repo=planning_repo,
            log=log,
            journal=journal,
            transcript=transcript,
            record_for=record_for,
            forge=forge,
            repo=repo,
        ),
        run_rework_review=build_run_review(
            planning_repo=planning_repo,
            forge=forge,
            model=models().rework_review,
            log=log,
            journal=journal,
            transcript=transcript,
            record_for=record_for,
            role="rework_review",
            repo=repo,
        ),
        # A rejected commit goes back to the build run's agent, same policy.
        commit=build_commit(
            unit_id=unit.id,
            fix=run,
            repo=repo,
            base=local_ref(repo.default_branch, repo=unit.repo),
        ),
        branch_commits=branch_commits,
        upstream_incomplete=build_upstream_incomplete(store),
        base_moved=build_base_moved(store),
        base_tip=tip,
        restack_onto=build_restack_onto(store, repo=repo),
        run_tier1=build_tier1(
            profile=profile,
            root_extras=repo.tests.root_extras,
            projects=repo.projects,
            log=log,
            repo=repo,
        ),
        on_flake=build_on_flake(store, installation, log=log),
        run_tier2=tier2.run,
        push=push_in_turn,
        open_pr=build_open_pr(store=store, log=log),
        linear=is_linear,
        post_status=tier2.post,
        close_pr=build_close_pr(),
        release_dependents=build_release_dependents(store, installation, log=log),
        remove_satisfied=build_remove_satisfied(store, installation, log=log),
        reply=build_post_replies(root=root, log=log, ui_replies=ui_reply_writer(root, store)),
        fetch_comments=build_fetch_comments(
            own=lambda repo, pr: own_posts(root, forges.key(forges.for_repo(repo)[1]), pr),
            extra_notes=ui_notes_of(installation, store),
            patch_of=unit_patch_of(installation, store),
        ),
        record_given=lambda repo, pr, ids: record_given_comments(
            root, forges.key(forges.for_repo(repo)[1]), pr, ids
        ),
        head=_head_sha,
        fetch=build_fetch(installation.checkouts, turn=lambda repo: repo_turn_of(repo)),
        fresh_base=build_fresh_base(store, record_merge=record_merge),
        log=log,
        log_reaches_run_log=log_reaches_run_log,
    )
