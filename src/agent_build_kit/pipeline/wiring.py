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
import hashlib
import logging
import os
import re
import shlex
import subprocess
import time
import uuid
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from agent_build_kit import claude_account, forges, infra, openspec, profiles, runtimes, sandboxes
from agent_build_kit.budget import Section, cut_head, cut_tail, fit
from agent_build_kit.config import (
    BASE_GROUP,
    CONFIG_ENV,
    CONFIG_FILENAME,
    REST_SPLIT,
    TEMPLATE_PLACEHOLDERS,
    E2eDimensionValue,
    E2eSplit,
    E2eUnitScope,
    ProjectConfig,
    RepoConfig,
    active,
    active_root,
    by_project,
    e2e_dimensions,
    e2e_splits,
    e2e_unit_scope,
    models,
    owning_project,
    stack_versions_for,
    unavailable_markers,
    worker_options,
)
from agent_build_kit.forges import FileChange, Forge, RegistersStacks, RepoId, StackRefused
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.path_patterns import matches_any
from agent_build_kit.pipeline import failure_evidence, spans
from agent_build_kit.pipeline.changelog_convention import review_changelog_paragraph
from agent_build_kit.pipeline.check_failures import failed_in
from agent_build_kit.pipeline.check_runner import worktree_at
from agent_build_kit.pipeline.command_limit import run_limited
from agent_build_kit.pipeline.commit_order import ALREADY_BUILT_TRAILER, branch_subjects
from agent_build_kit.pipeline.config_guard import config_unchanged
from agent_build_kit.pipeline.determinism_guidance import determinism_guidance
from agent_build_kit.pipeline.e2e import (
    UNKNOWN_SPLIT,
    E2eClassification,
    E2eResult,
    E2eSelection,
    E2eVerdict,
    TestFailure,
    TestTime,
    build_selection,
    build_snapshot,
    needs_text,
    selection_unavailable,
    stack_lock,
)
from agent_build_kit.pipeline.e2e import (
    post_status as e2e_post_status,
)
from agent_build_kit.pipeline.e2e_holds import repo_holds
from agent_build_kit.pipeline.e2e_schedule import is_scheduled
from agent_build_kit.pipeline.e2e_times import record_test_times, with_split
from agent_build_kit.pipeline.environment import (
    artifact_patterns,
    lock_paths,
    restore_unchanged_locks,
    unstage_artifacts,
    unstage_untracked_locks,
)
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.fix_reproduction import (
    Attempt,
    Outcome,
    Reproduction,
)
from agent_build_kit.pipeline.fix_reproduction import check as check_reproduction
from agent_build_kit.pipeline.flakes import (
    FailedOnBase,
    Flake,
    FlakeFound,
    OnFlake,
    covered_tests,
    flake_record,
    record_storm,
)
from agent_build_kit.pipeline.gateway_usage import Spend, attribution, configured_source
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.moved_base import moved_base_scope
from agent_build_kit.pipeline.own_tests import (
    defined_tests_in_range,
    failed_ids,
    tests_in,
    written_by_unit,
)
from agent_build_kit.pipeline.pending import describe, pending_projects
from agent_build_kit.pipeline.planning_repo import current_branch
from agent_build_kit.pipeline.planning_sync import in_repo_name
from agent_build_kit.pipeline.pr_replies import (
    MARKER,
    build_post_replies,
    own_posts,
    record_given_comments,
)
from agent_build_kit.pipeline.product_defect import (
    ProductDefect,
    ProductDefectEntry,
    product_defect_record,
    wait_on_product_defect,
)
from agent_build_kit.pipeline.regression_agent import (
    FixKind,
    RegressionRunCapped,
    wait_on_regression,
)
from agent_build_kit.pipeline.restack import (
    EmptyBranchBlocked,
    HostMoved,
    Moved,
    Resolver,
    RestackConflict,
    Turn,
    adopt_host_head,
    diff_id,
    move_branch_onto,
    push_with_lease,
    remote_head,
    resolved_move,
    retried_once,
)
from agent_build_kit.pipeline.review_paths import is_protected
from agent_build_kit.pipeline.run_log import (
    TestRun,
    append_e2e_output,
    append_test_run,
    e2e_output_dir,
    failure_bundles_dir,
    run_ledger_path,
    write_failure_bundle,
    write_rerun_evidence,
)
from agent_build_kit.pipeline.scratch import run_folder, selection_seed
from agent_build_kit.pipeline.shell import changed_files, git, git_out, has_origin, porcelain
from agent_build_kit.pipeline.stack_runner import FixResult, Restacked, UnitRunner, Worktree
from agent_build_kit.pipeline.transcript import Transcript, TranscriptEvent, transcript_dir
from agent_build_kit.pipeline.ui_review import ui_notes_of, ui_reply_writer, unit_patch_of
from agent_build_kit.pipeline.unit_size import actual_lines, branch_diff, over_ceiling, unit_ceiling
from agent_build_kit.pipeline.unit_store import (
    Cause,
    Pull,
    StoredUnit,
    UnitStore,
    unit_id_of_branch,
)
from agent_build_kit.pipeline.units import (
    BUILDS_NOTHING,
    IN_REVIEW,
    MERGED,
    PLANNED,
    REVIEWED,
    RUNNING,
    Unit,
    base_of,
    branch_name,
    followed_dependencies,
    local_ref,
    through_satisfied,
    trunk_of,
)
from agent_build_kit.pipeline.untouched_failures import (
    PreExisting,
    holding_fixes,
    preexisting_record,
    wait_on_change,
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
from agent_build_kit.profiles.base import (
    TEMP_ROOT_VARIABLE,
    AppliesE2eSelection,
    AppliesFixers,
    ProjectChecks,
    RecordsSelectionData,
    RepeatsTests,
    ReportsRunFacts,
    SelectsAffectedTests,
    SetsTestEnvironment,
    ToolchainProfile,
    is_doc_path,
    located,
)
from agent_build_kit.redaction import WITHHELD, redact_leaves, redact_text
from agent_build_kit.runtimes import AgentRequest, AgentRuntime, ToolPolicy
from agent_build_kit.runtimes.base import PermissionMode, Role, SessionUnavailable
from agent_build_kit.runtimes.claude_code import through
from agent_build_kit.sandboxes import Coverage, SandboxPolicy, step_confined
from agent_build_kit.sandboxes.confinement import SandboxRefused
from agent_build_kit.sandboxes.policy import PolicyRefused, build_policy

logger = logging.getLogger(__name__)

Run = Callable[..., subprocess.CompletedProcess]

# How many times the failed tests are run again, alone, before they count as a flake.
FLAKE_RERUNS = 2
# How much of a flaky test's own failure section is kept, and how many of a storm's tests keep
# theirs, each cut to how many characters; all from the end, where the error is.
FLAKE_FAILURE_CHARS = 6000
STORM_FAILURES = 3
STORM_FAILURE_CHARS = 3000

# A unit's e2e-test output: how much is kept, what a passing command's section may take, how
# much of a failed test's own section its line in the digest keeps, and how much more a
# failed command weighs than a passing one.
E2E_OUTPUT_CHARS = 4000
E2E_PASSING_CHARS = 1500
E2E_DIGEST_CHARS = 300
E2E_FAILED_WEIGHT = 4
# How much of the output the failed commands' digests may reserve between them.
E2E_DIGEST_SHARE = E2E_OUTPUT_CHARS * 3 // 4
# What a command's section keeps at least, beside its header: the end of its output, or the
# start of its failure digest, so a section can always get what its smallest form says.
E2E_SMALLEST_TAIL = 200


def _failure_digest(toolchain: ToolchainProfile, text: str) -> str:
    """Each failed test's identifier and the end of its own section, where the error is;
    empty when the profile cannot read the failed tests."""
    tests = failed_ids(toolchain, text)
    if not tests:
        return ""
    found = _failure_sections(toolchain, text)
    return "\n".join(
        "\n".join(part for part in (test, cut_tail(found.get(test, ""), E2E_DIGEST_CHARS)) if part)
        for test in tests
    )


def _command_section(
    header: str, text: str, toolchain: ToolchainProfile, *, failed: bool, failures: int = 1
) -> Section:
    """One command's part of the e2e-test output. A passing command keeps the end of its
    output; a failed one keeps its failed tests and why first, then the end of the rest. A
    failed command is never left out, and reserves its digest up to its part (of `failures`
    commands) of `E2E_DIGEST_SHARE`."""
    digest = _failure_digest(toolchain, text) if failed else ""
    full = f"{header}\n{text}"
    front = len(header) + 1
    reserve = max(E2E_DIGEST_SHARE // failures, E2E_SMALLEST_TAIL)

    def render(size: int) -> str:
        room = size - front
        if size >= len(full):
            return full
        if digest and len(digest) >= room:
            return f"{header}\n{cut_head(digest, max(room, 0), 'line')}"
        if digest:
            rest = cut_tail(text, room - len(digest) - 1, "line") if room > len(digest) + 1 else ""
            return f"{header}\n{digest}" + (f"\n{rest}" if rest else "")
        return f"{header}\n{cut_tail(text, max(room, 0), 'line')}"

    return Section(
        key=header,
        render=render,
        natural=len(full),
        smallest=min(len(full), front + min(len(digest) or E2E_SMALLEST_TAIL, reserve)),
        weight=E2E_FAILED_WEIGHT if failed else 1,
        ceiling=None if failed else front + E2E_PASSING_CHARS,
        required=failed,
    )


# Told a finished agent call: `(result, *, role, model, runtime)`, and `gateway`
# (a function giving the run's `Spend`) when a gateway key was minted for it.
AgentCallback = Callable[..., None]

# The code host is read-only for agents: the forge names the commands that read
# a PR (`read_commands`). What they have to say on a PR the pipeline posts after
# the push (see `pr_replies`), as the account that owns the repo. The
# toolchain's own commands (a test runner, a linter) come from the profile.
BASE_TOOLS = "Read Edit Write Grep Glob Bash(git *)"

# Only a builder installs a staged config file through the kit (the reviewer's list is its own).
INSTALL_CONFIG_TOOL = "Bash(abk install-config *)"


# A builder raises a step only a person can do, with a check script it wrote.
MANUAL_TOOL = "Bash(abk manual *)"


def forge_read_tools(forge: Forge) -> str:
    return " ".join(f"Bash({' '.join(command)}*)" for command in forge.read_commands)


def allowed_tools(
    profile: ToolchainProfile, forge: Forge, projects: list[ProjectConfig] | None = None
) -> str:
    """The repo profile's tools and those of each project's profile, each listed once."""
    toolchains = [profile, *(profiles.get(p.profile) for p in projects or [])]
    tools = dict.fromkeys(t.allowed_tools for t in toolchains)
    own = f"{BASE_TOOLS} {INSTALL_CONFIG_TOOL} {MANUAL_TOOL}"
    return f"{own} {forge_read_tools(forge)} {' '.join(tools)}".strip()


def _planning_root(planning_repo: Path | None) -> Path:
    root = planning_repo or active_root()
    if root is None:
        raise RuntimeError("no planning repo: load an installation (abk.yaml) first")
    return root


def _specs_dir(planning_repo: Path | None) -> Path:
    return _planning_root(planning_repo) / active().planning.specs_dir


def _run_limited(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """The default runner for unit-test: `_run` under the configured command time limit."""
    limits = active().global_limits
    return run_limited(
        args,
        limit=limits.unit_test_command_seconds,
        grace=limits.unit_test_abort_grace_seconds,
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
    here = current_branch(cwd)
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
        result_limit=active().global_limits.transcript_result_chars,
        runs_kept=active().global_limits.transcript_runs_kept,
    )


def sandbox_policy(
    repo: str,
    worktree: Path,
    runtime: AgentRuntime,
    account: claude_account.Account | None,
    tier: TestTier = TestTier.UNIT_TEST,
    changes: tuple[str, ...] = (),
    log: Callable[[str], None] = print,
) -> SandboxPolicy | None:
    """The policy a step in `worktree` of `repo` runs under; None while the sandbox is off, the
    call is not a step of a repo, or no backend exists for this platform (said once through
    `log`). A backend that matches the platform but fails its probe stops the step."""
    root = active_root()
    if not active().sandbox.enabled or not repo or root is None:
        return None
    backend, found = sandboxes.probe(active().sandbox.backend)
    if not found.ok and sandboxes.no_backend(backend):
        log(f"sandbox: this step runs unconfined: {found.cause} ({found.fix})")
        return None
    if not found.ok and active().repos[repo].sandbox.required is not Coverage.NONE:
        # Raised as a refusal so the caller revokes the step's gateway key before it stops.
        raise PolicyRefused(
            f"sandbox backend {backend.name} does not work: {found.cause}; {found.fix}"
        )
    return build_policy(
        Installation(active(), root),
        repo,
        worktree,
        runtime=runtime,
        profile=profiles.get(active().repos[repo].profile),
        account=account,
        tier=tier,
        changes=changes,
    )


# The roles whose reply is a verdict on a branch.
REVIEW_ROLES: tuple[Role, ...] = ("review", "rework_review")

SANDBOX_DENIAL = re.compile(r"EACCES|permission denied", re.IGNORECASE)


def denied_paths(line: str) -> list[str]:
    """The absolute paths in an event `line` that says a read was denied; none when it does not."""
    if not SANDBOX_DENIAL.search(line):
        return []
    return [found.rstrip(".,;") for found in re.findall(r"/[^\s'\":,;()]+", line)]


def refused_read(line: str, specs: Path) -> str | None:
    """The path under `specs` that a step's event `line` says the sandbox refused, if it does."""
    return next((p for p in denied_paths(line) if Path(p).is_relative_to(specs)), None)


def refused_exec(line: str, granted: Iterable[Path]) -> str | None:
    """The path a denial in a step's event `line` names that the policy grants neither to read
    nor to write: a command or a read the sandbox refused. A denial of a path the policy grants
    (a file mode, say) is not the sandbox's."""
    folders = tuple(granted)
    # The policy's entries are resolved; a denial prints the path as the command spelled it.
    return next(
        (
            p
            for p in denied_paths(line)
            if not any(Path(p).resolve().is_relative_to(f) for f in folders)
        ),
        None,
    )


def refused_git_read(line: str) -> str | None:
    """The path a `git` failure `line` says the sandbox refused, if it does: a fatal message
    with a denial and an absolute path."""
    if not line.lstrip().startswith("fatal:"):
        return None
    return next(iter(denied_paths(line)), None)


def build_run(
    *,
    sandbox_repo: str = "",
    sandbox_tier: TestTier = TestTier.UNIT_TEST,
    sandbox_changes: tuple[str, ...] = (),
    run: Run | None = None,
    planning_repo: Path | None = None,
    allowed_tools: str | None = None,
    log: Callable[[str], None] | None = None,
    journal: Callable[[str], None] | None = None,
    transcript: Callable[[str], None] | None = None,
    record_for: tuple[Unit, Path, datetime] | None = None,
    runtime: AgentRuntime | None = None,
    role: Role = "implement",
    planning_paths: tuple[str, ...] = (),
    account: claude_account.Account | None = None,
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
    planning_root = _planning_root(planning_repo)
    specs = planning_root / active().planning.specs_dir
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
        tools: str = "",
        permission_mode: PermissionMode = "edit",
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
        try:
            sandbox = sandbox_policy(
                sandbox_repo, cwd, agent, account, sandbox_tier, sandbox_changes, log or print
            )
        except PolicyRefused as refused:
            spend()
            raise RuntimeError(f"the sandbox policy was refused: {refused}") from refused
        if sandbox is not None and not agent.sandbox_coverage.reaches(sandbox.required):
            (log or print)(
                f"sandbox: {agent.name} confines {agent.sandbox_coverage.value} of a step, less "
                f"than the {sandbox.required.value} this repo requires; the step runs unconfined"
            )
        # A step that ran under a policy was confined at least to what the repo requires (the
        # launcher refuses less); under `required: none` it may have run plain.
        is_confined = sandbox is not None and step_confined(
            sandbox.required, agent.sandbox_coverage
        )
        recorder = _recorder(record_for, place, role)

        git_refused: list[str] = []

        def record(made: TranscriptEvent) -> None:
            if recorder:
                recorder.record(made)
            if made.kind != "tool_result":
                return
            for line in made.text.splitlines():
                if (denied := refused_git_read(line)) is not None:
                    git_refused.append(denied)
                if (path := refused_read(line, specs)) is not None:
                    (log or print)(f"sandbox: the sandbox does not let this step read {path}")
                elif (
                    is_confined
                    and sandbox is not None
                    and (path := refused_exec(line, (*sandbox.read, *sandbox.write)))
                ):
                    (log or print)(
                        f"sandbox: the sandbox does not let this step read or run {path}"
                    )

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
            account=account,
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
            # A call may narrow what it is granted (the restack's resolution, in a paused rebase).
            allowed_tools=tools or allowed_tools or BASE_TOOLS,
            permission_mode=permission_mode,
            policy=ToolPolicy(
                specs_dir=specs,
                branch_prefix=active().git.branch_prefix,
                planning_paths=planning_paths,
                # The review policy in abk.yaml is a person's: no command writes it.
                fenced_files=(planning_root / CONFIG_FILENAME,),
                sandbox=sandbox,
                confined=is_confined,
                # The pipeline commits what the step leaves in the worktree, with the lint gate,
                # the unit-id trailer and the group's subject; an agent commit skips all three.
                no_commit=True,
            ),
            on_event=journal or log or print,
            on_transcript=transcript,
            on_record=record if is_confined else (recorder.record if recorder else None),
        )
        try:
            # Its own folder for long command output, gone when the run ends:
            # nothing one agent wrote reaches another.
            with run_folder(cwd) as out:
                if out is not None:
                    request = request.model_copy(update={"env": {**env, "ABK_OUT": str(out)}})
                    if sandbox is not None and request.policy is not None:
                        # The run folder is made after the request: the step writes there.
                        granted = sandbox.model_copy(
                            update={"write": (*sandbox.write, out.resolve())}
                        )
                        policy = request.policy.model_copy(update={"sandbox": granted})
                        request = request.model_copy(update={"policy": policy})
                # Neither configuration file may differ afterwards, whatever route a write took.
                # A confined step cannot have written them: a difference is a person's edit.
                confined = sandbox.required if is_confined and sandbox else Coverage.NONE
                state_dir = Installation(active(), planning_root).state_dir
                with config_unchanged(
                    planning_root, confined, state_dir=state_dir, warn=log or print
                ):
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
        if role in REVIEW_ROLES and git_refused:
            # A policy fault, not a verdict: the reviewer could not run git, so what it says
            # about the branch is not a review.
            raise SandboxRefused(f"the sandbox does not let the review's git read {git_refused[0]}")
        if not result.ok:
            # Half-finished edits are on disk: carrying on would commit them.
            raise RuntimeError(result.error)
        return result.text

    return run_agent


# The reviewer reads and judges; it does not edit. Anything it wants changed it
# says, and the build step makes the change — so its judgement is not limited to
# what it can safely rewrite itself, and a concern it can only articulate
# ("this leaks under concurrency") reaches someone instead of being discarded.
REVIEW_PROMPT = (
    """\
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
- **Search for prior art.** For each new function, constant, pattern or test
  helper in the diff, search the repository for an existing equivalent and the
  diff for a second copy, and name the existing one by file and line. A stub or
  helper added by the tests commit counts as added by the change. A test
  repointed at an existing function with unchanged assertions is not a finding.
  A duplicate the change introduces or makes worse is a required finding: its
  consequence is that two copies must change together, and done is to use or
  extend the existing one, or extract one shared function. Parallel call sites
  and per-variant copies (two hosts, backends or runtimes) are the common
  cases. This states the consequence a required finding needs. Duplication the
  change neither adds to nor extends is not yours to report.
- **Tests listed `possible` under Same exposure.** When the change's tasks carry a line naming
  tests as possible, an edit to one of those tests is in scope if the commit body names the test
  and the evidence that it shares the cause. It is a required change when that evidence is
  missing, and an edit to a test that the tasks neither name in a step nor list as possible is a
  required change to remove it.
- **Hold the tests to the determinism rules.** """
    + determinism_guidance()
    + """ A use of
  any of these that the change introduces is a required finding, and its
  consequence is that the test passes alone and fails under load.
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

When you approve, also give a `description` of the whole branch, written for
someone who has not seen the spec and worked out from the diff: a one-sentence
`summary` and three to six `changes`, each a behaviour the branch adds or alters,
behaviour first, naming a file only where that helps and saying nothing about
files the branch does not change. It rides in the same reply; do not run anything extra for it.

Reply with JSON and nothing else:
{"approved": true|false, "feedback": "anything that is not a finding, empty when approved",
 "findings": [{"file": "path", "line": 12, "summary": "...", "consequence": "...",
               "done": "...", "required": true|false}],
 "earlier": [{"id": "1.1", "status": "fixed|open|declined"}],
 "needs_human": false,
 "follow_ups": [{"kind": "optional|correctness|test_passes_regardless|missing_test|policy",
                 "point": "..."}],
 "escalate": "", "reasoning": "",
 "description": {"summary": "...", "changes": ["..."]}}
"""
)

# What review adds to the prompt when it is enabled: the classification the reviewer gives.
REVIEW_CLASSIFICATION_PROMPT = """\
**Classify the review this unit deserves.** Besides your verdict, give a `classification`
of `auto`, `light` or `full`: how much review a person should give the finished change.
Judge it by three criteria: whether the change crosses a boundary another system depends
on, whether it is hard to undo, and what behaviour the tests do not exercise. A change that
does none of these is `auto`; one that does a little is `light`; the rest is `full`. Your
classification can raise the review a unit gets and never lower it: the planned estimate and
the checks keep their floors whatever you say. When your classification is above the unit's
planned estimate, give `drivers`, the groups or files that account for it. A classification
is not an escalation: `needs_human` and `escalate` answer a different question, whether a
person must decide something now, and neither changes the classification. Put both in the
JSON reply below as "classification": "auto|light|full" and "drivers": ["group or file"].

"""

# Read-only. The reviewer physically cannot edit the branch, so the separation
# between judging and authoring is enforced rather than asked for.
REVIEW_TOOLS = "Read Grep Glob Bash(git diff*) Bash(git log*) Bash(git show*)"


def build_run_review(
    *,
    sandbox_repo: str = "",
    sandbox_changes: tuple[str, ...] = (),
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
    account: claude_account.Account | None = None,
) -> Callable[..., str]:
    """The review pass. Separate from implementation so the standards are
    loaded only here, not during the expensive run."""
    inner = build_run(
        sandbox_repo=sandbox_repo,
        sandbox_changes=sandbox_changes,
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
        account=account,
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
        prompt = (
            REVIEW_CLASSIFICATION_PROMPT + REVIEW_PROMPT + review_changelog_paragraph(cwd, repo)
        )
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


def with_trailers(message: str, *, unit_id: str, adopted_from: str, built: bool = False) -> str:
    """`message` followed by the trailer block a unit's commits carry: the unit, the chat
    session adopted from, and for a group recorded as built the mark, last."""
    trailers = (
        ([f"Unit: {unit_id}"] if unit_id else [])
        + ([f"Adopted-From: {adopted_from}"] if adopted_from else [])
        + ([f"{ALREADY_BUILT_TRAILER}: yes"] if built else [])
    )
    return f"{message}\n\n" + "\n".join(trailers) + "\n" if trailers else message


def build_commit(
    *,
    unit_id: str = "",
    run: Run | None = None,
    fix: Callable[..., str] | None = None,
    adopted_from: str = "",
    gate: Callable[[Path], str] | None = None,
    repo: RepoConfig | None = None,
    base: str = "",
    only: Sequence[str] | None = None,
) -> Callable[..., int]:
    """Commit what the tree holds (or, with `only`, what it holds under those pathspecs),
    reporting how many commits resulted.

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

    `only` limits the commit to those pathspecs: nothing else is staged, checked or
    committed, and what else the tree holds is left as it was: modified files stay modified,
    and staged ones stay staged.
    """
    run = run or _run

    default_base = base

    def commit(message: str, *, cwd: Path, base: str = "") -> int:
        # The unit id in the trailer keeps a branch's history readable without
        # the planning repo open beside it.
        body = with_trailers(message, unit_id=unit_id, adopted_from=adopted_from)

        def attempt() -> subprocess.CompletedProcess | None:
            restore_unchanged_locks(repo, cwd, base or default_base)
            if only is None:
                run(["git", "add", "-A"], cwd=cwd)
            elif names := [name for _, name in porcelain(cwd, *only)]:
                # The changed paths under the pathspecs, not the pathspecs: git refuses
                # `add` when one of them matches nothing.
                run(["git", "add", "-A", "--", *names], cwd=cwd)
            unstage_untracked_locks(repo, cwd)
            unstage_artifacts(repo, cwd)
            # With `only`, what was staged outside the pathspecs is neither counted nor
            # committed: it stays staged.
            scope = ["--", *only] if only is not None else []
            if not run(["git", "diff", "--cached", "--quiet", *scope], cwd=cwd).returncode:
                return None  # Nothing staged: an empty commit would be a lie.
            if gate is not None and (rejected := gate(cwd)):
                return subprocess.CompletedProcess(["gate"], 1, stdout=rejected, stderr="")
            if only is None:
                return run(["git", "commit", "-q", "-m", body], cwd=cwd)
            staged = run(
                ["git", "diff", "--cached", "--name-only", "--no-renames", *scope], cwd=cwd
            ).stdout
            return run(["git", "commit", "-q", "-m", body, "--", *staged.splitlines()], cwd=cwd)

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


def build_commit_built(
    *,
    unit_id: str = "",
    run: Run | None = None,
    adopted_from: str = "",
) -> Callable[..., int]:
    """The runner's `commit_built(message, *, cwd)`: an empty commit marking a group built.

    Hooks run, and the gate does not; one attempt, since a rejected empty commit leaves
    nothing for an agent to change."""
    run = run or _run

    def commit_built(message: str, *, cwd: Path) -> int:
        body = with_trailers(message, unit_id=unit_id, adopted_from=adopted_from, built=True)
        result = run(["git", "commit", "-q", "--allow-empty", "-m", body], cwd=cwd)
        if result.returncode:
            raise CommitRejected(
                f"git commit was rejected in {cwd}:\n{result.stdout}\n{result.stderr}".strip()
            )
        return 1

    return commit_built


def build_stub_checks(
    *,
    profile: ToolchainProfile,
    projects: list[ProjectConfig] | None = None,
    run: Callable[..., subprocess.CompletedProcess] | None = None,
) -> Callable[..., tuple[bool, str]]:
    """The static checks of a stubbed build's test step: lint, format and types over the
    tree with its new files staged, and no test.

    The command is the clean command the push gate runs at the tests commit, with types,
    run in the directory of each project the changed files belong to."""
    run = run or _run

    def checks(*, cwd: Path) -> tuple[bool, str]:
        # Staged so the checkers, which read what git tracks, see a file the agent added.
        run(["git", "add", "-A"], cwd=cwd)
        names = run(["git", "diff", "--cached", "--name-only"], cwd=cwd).stdout.split()
        failures: list[str] = []
        for owner, _ in by_project(projects or [], names) or [(None, [])]:
            toolchain = profiles.for_project(owner, profile)
            where = cwd / owner.prefix if owner else cwd
            clean = ["sh", "-c", toolchain.clean_command(types=True)]
            done = run(located(toolchain, clean, where, cwd), cwd=where)
            if done.returncode:
                failures.append(f"{done.stdout}\n{done.stderr}".strip())
        return not failures, "\n\n".join(failures)

    return checks


def build_fixers(
    *,
    profile: ToolchainProfile,
    projects: list[ProjectConfig] | None = None,
    repo_name: str,
    run: Callable[..., subprocess.CompletedProcess] | None = None,
) -> Callable[..., FixResult]:
    """The runner's `run_fixers(*, cwd)`: the unit's own changed and untracked files, per
    project, through the repo's fix command or the profile's.

    The files are the ones a commit is about to stage, less the lock files and artifacts it
    unstages and the ones the review policy protects. The exit status is ignored: a fixer
    exits non-zero for what it changed or could not fix, so what it did is read from the
    files. A command that cannot run is reported and the build goes on."""
    run = run or _run

    def run_fixers(*, cwd: Path) -> FixResult:
        repo = active().repos.get(repo_name)
        setting = repo.tests.fix_command if repo else None
        if setting is not None and not setting:
            return FixResult()
        skip = (*lock_paths(repo, cwd), *artifact_patterns(repo, cwd))
        names = [
            name for code, name in porcelain(cwd) if "D" not in code and not matches_any(skip, name)
        ]
        protected = [name for name in names if is_protected(active(), repo_name, name)]
        names = [name for name in names if name not in protected]
        skipped = dict.fromkeys(protected)
        # Protected files as they are now, the unit's changed ones and the committed ones a
        # hook might rewrite although it was not given them.
        held = {
            name: (cwd / name).read_bytes() if (cwd / name).is_file() else None
            for name in {*git_out(cwd, "ls-files").splitlines(), *protected}
            if is_protected(active(), repo_name, name)
        }
        present = {name for _, name in porcelain(cwd)}
        given: dict[str, None] = {}
        changed: dict[str, None] = {}
        failed: list[str] = []
        for owner, relative in by_project(projects or [], names):
            toolchain = profiles.for_project(owner, profile)
            prefix = owner.prefix if owner else ""
            if setting is not None:
                command = [*setting, *relative]
            else:
                command = (
                    toolchain.fix_command(relative)
                    if isinstance(toolchain, AppliesFixers)
                    else None
                )
            if not command:
                continue
            if setting is None:
                command = located(toolchain, command, cwd / prefix, cwd)
            files = [f"{prefix}{name}" for name in relative]
            given.update(dict.fromkeys(files))
            first = {name: _digest(cwd / name) for name in files}
            last = first
            for _ in range(FIXER_PASSES):
                try:
                    run(command, cwd=cwd / prefix)
                except OSError as exc:
                    failed.append(f"{command[0]}: {exc}")
                    break
                now = {name: _digest(cwd / name) for name in files}
                moved = now != last
                last = now
                if not moved:
                    break
            changed.update(dict.fromkeys(name for name in files if last[name] != first[name]))
        for name, content in held.items():
            target = cwd / name
            if (target.read_bytes() if target.is_file() else None) != content:
                if content is None:
                    target.unlink()
                else:
                    target.write_bytes(content)
                skipped[name] = None
        # A protected file a hook created from nothing is taken away, or the next commit
        # would stage it.
        for _, name in porcelain(cwd):
            if name not in present and is_protected(active(), repo_name, name):
                (cwd / name).unlink(missing_ok=True)
                skipped[name] = None
        return FixResult(
            given=tuple(given),
            changed=tuple(changed),
            skipped=tuple(skipped),
            failed=tuple(failed),
        )

    return run_fixers


# The passes a project's fixers make at most: a second covers a hook that reformats the
# first one's output, and no loop is needed beyond it.
FIXER_PASSES = 2


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def build_tree_state(*, run: Callable[..., subprocess.CompletedProcess] | None = None):
    """A digest of a working tree, new files included: what says whether a fix changed it."""
    run = run or _run

    def state(cwd: Path) -> str:
        run(["git", "add", "-A"], cwd=cwd)
        return run(["git", "write-tree"], cwd=cwd).stdout.strip()

    return state


def branch_commits(repo: Path, base: str, head: str = "HEAD") -> int:
    """How many commits the branch (`head`, the checked-out one by default) carries beyond
    its base.

    The question a resumed unit asks: not "did this run write anything" but
    "is the work there". A git failure raises rather than counting as none:
    "no commits of its own" can end a unit as satisfied, so an unresolvable
    base must not read as that.
    """
    return int(git_out(repo, "rev-list", "--count", f"{base}..{head}"))


# How many tokens a run draws before it gives up finding one whose folder is free.
RUN_TOKEN_TRIES = 20


def build_unit_test(
    *,
    run: Run | None = None,
    changed: Callable[..., list[str]] | None = None,
    profile: ToolchainProfile | None = None,
    root_extras: list[str] | None = None,
    projects: list[ProjectConfig] | None = None,
    log: Callable[[str], None] | None = None,
    repo: RepoConfig | None = None,
    failures_dir: Path | None = None,
    now: Callable[[], datetime] | None = None,
    machine: Callable[[], dict[str, object]] | None = None,
    installation: Installation | None = None,
    test_runs: Path | None = None,
) -> Callable[..., tuple[bool, str]]:
    """Lint the unit's own diff, then test the members it reaches.

    Each command it runs is logged with where it ran and how it ended, so a
    pass can be checked against CI afterwards: a unit-test that passed on a branch
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
    that make a unit satisfied are the repo's real unit-test, not an empty scope.
    """
    run = run or _run_limited
    changed = changed or changed_files
    profile = profile or profiles.get("python-uv")
    clock = now or (lambda: datetime.now(UTC))
    affected = (
        repo.checks.affected if repo is not None and repo.checks.affected.mode != "off" else None
    )
    # The repo's worker settings, handed to the profile beside `root_extras`.
    worker_settings: dict[str, Any] = (
        {"workers": repo.tests.workers, "max_workers": repo.tests.max_workers}
        if repo is not None
        else {}
    )
    # Per unit: the test time and count of its last full run.
    last_full: dict[str, tuple[float, int]] = {}
    # The tests of a round recorded as a storm, so a later command that fails them is not rerun.
    stormed: dict[tuple[str, str, str, int], set[str]] = {}
    # The checkout the current run is in: where a check's configuration is looked for up to.
    checkout: dict[str, Path] = {}
    # This run's token, and the environment each profile that sets one gave its commands.
    run_token: dict[str, str] = {}
    run_environments: dict[str, dict[str, str]] = {}
    # What the current run's test commands asked for, for its ledger row.
    run_facts: dict[str, object] = {}
    # The tests the current run's failed commands named, each read by the profile of the
    # command (a project has its own), for its ledger row.
    run_failed: list[str] = []

    def fresh_run_token() -> str:
        """A token for this run whose folder in the temp root does not exist, so two runs never
        share a folder: the second would overwrite the first's pid file and `run.json`, and a
        sweep could judge the first run by the second's process."""
        for _ in range(RUN_TOKEN_TRIES):
            token = uuid.uuid4().hex[:8]
            if installation is None or not (installation.pytest_temp_root / token).exists():
                return token
        raise RuntimeError(f"no free run token in {RUN_TOKEN_TRIES} tries; the temp root is full")

    def unit_test(
        *,
        cwd: Path,
        base: str,
        whole_repo: bool = False,
        failed_output: str = "",
        moved_from: str | None = None,
    ) -> tuple[bool, str]:
        """`tested`, with a row added to the ledger of unit-test runs when one is kept: the run
        passing, failing or finding a flake."""
        if test_runs is None:
            return tested(cwd, base, whole_repo, failed_output, moved_from)
        sample = machine or failure_evidence.machine_sample
        started = clock()
        load_start = _first_load(sample())
        run_facts.clear()
        run_failed.clear()
        outcome = "failed"
        failed: list[str] = []
        try:
            passed, output = tested(cwd, base, whole_repo, failed_output, moved_from)
        except FlakeFound as found:
            outcome, failed = "flake", [flake.test for flake in found.flakes]
            raise
        except FailedOnBase as found_on_base:
            failed = [failure.test for failure in found_on_base.failures]
            raise
        else:
            outcome = "passed" if passed else "failed"
            failed = [] if passed else list(run_failed)
            return passed, output
        finally:
            ended = clock()
            workers = run_facts.get("workers_setting")
            try:
                append_test_run(
                    test_runs,
                    TestRun(
                        unit=spans.current_unit.get()[0],
                        started=started.isoformat(),
                        seconds=(ended - started).total_seconds(),
                        outcome=outcome,
                        failed=failed,
                        load_start=load_start,
                        load_end=_first_load(sample()),
                        workers=None if workers is None else str(workers),
                        tick=spans.PROCESS_TICK,
                        units_running=_running_units(installation),
                    ),
                )
            except OSError as error:
                # A record of the run must not replace the run's own result.
                _say(log, f"unit-test: the run was not added to the ledger ({error})")

    def tested(
        cwd: Path,
        base: str,
        whole_repo: bool,
        failed_output: str,
        moved_from: str | None,
    ) -> tuple[bool, str]:
        """(passed, what failed) — the output is what makes a retry useful.

        `failed_output` is the output of the failed check a fix is answering; given,
        and the repo's affected-tests mode on, the tests run are the selected ones.
        `moved_from` is the base a clean move left (empty when it had none; None when the run
        follows no move), which says whether the run is scoped
        by what the move can affect; the line it logs says which it was and why."""
        checkout["root"] = cwd
        run_token["id"] = fresh_run_token()
        run_environments.clear()
        # What an earlier run of this unit round stormed does not excuse this run's failures.
        stormed.pop(spans.current_unit.get(), None)
        for project in pending_projects(cwd, projects):
            _say(log, describe(project))
        scope = None
        if moved_from is not None:
            scope = moved_base_scope(
                cwd,
                own=changed(cwd, base),
                base=base,
                moved_from=moved_from,
                setting=active().global_limits.restack_check,
            )
        work = _work(cwd, base, whole_repo, projects, profile, changed)
        if projects and not work:
            _say(log, "every project is pending, nothing ran in a project")
            if whole_repo:
                # No diff to be judged by: a unit that produced nothing for the declared
                # projects to check is not satisfied by their absence.
                names = ", ".join(p.path for p in pending_projects(cwd, projects))
                return False, (
                    f"every declared project is pending ({names}) and the unit produced "
                    "nothing for them to judge"
                )
            return root_checks(cwd)
        if scope is not None and scope.scoped and not whole_repo:
            moved = moved_run(cwd, base, work, scope.incoming)
            if moved is not None:
                return moved
        elif scope is not None:
            _say(log, f"moved base: ran the full suite ({scope.reason})")
        plan = None
        if affected is not None and not whole_repo and failed_output.strip():
            plan = selection(base, work, failed_output)
        if plan is None:
            return full(cwd, base, work, whole_repo, lint=True)
        earlier = last_full.get(spans.current_unit.get()[0])
        figures: list[tuple[float, int]] = []
        selected = run_selection(plan, figures, base=base)
        if selected is not None and not selected[0]:
            record_selected(figures, "not_run", earlier)
            return selected
        # A selected pass is not the green: the full tests confirm it, and lint runs again
        # unless the selection got through it for every project.
        confirmed = full(cwd, base, work, whole_repo, lint=selected is None)
        if selected is not None:
            record_selected(figures, "agreed" if confirmed[0] else "disagreed", earlier)
        if selected is not None and not confirmed[0]:
            _say(
                log,
                "affected tests: the selected tests passed and the full suite failed, "
                "a disagreement",
            )
        return confirmed

    def moved_run(
        cwd: Path,
        base: str,
        work: list[tuple[Path, ToolchainProfile, list[str]]],
        incoming: list[str],
    ) -> tuple[bool, str] | None:
        """A scoped moved base: lint, the tests the unit added or changed, and the tests the
        profile names for the unit's files with the files the move brought in. None, with
        the reason logged, when the full suite has to stand in."""
        plan, owned, own_ids, reason = moved_plan(cwd, base, work, incoming)
        if plan is None:
            _say(log, f"moved base: ran the full suite ({reason})")
            return None
        earlier = last_full.get(spans.current_unit.get()[0])
        figures: list[tuple[float, int]] = []
        why: list[str] = []
        flaked: list[Flake] = []
        outcome = run_selection(plan, figures, why, own_ids, flaked, base=base)
        if outcome is None:
            _say(log, f"moved base: ran the full suite ({why[0]})")
            return None
        if not outcome[0]:
            return outcome
        record_selected(figures, "moved", earlier)
        counts = [count for _, count in figures]
        own = sum(sum(counts[start : start + length]) for start, length in owned)
        total = f" of {earlier[1]}" if earlier else ""
        _say(
            log,
            f"moved base: ran {sum(counts)}{total} tests (own {own}, affected {sum(counts) - own})",
        )
        checked = root_checks(cwd, [(where, toolchain, []) for where, toolchain, _ in plan])
        if flaked and checked[0]:
            # Everything else passed: the flakes are all that is left to say.
            raise FlakeFound(tuple(flaked), scoped=True)
        return checked

    def moved_plan(
        cwd: Path,
        base: str,
        work: list[tuple[Path, ToolchainProfile, list[str]]],
        incoming: list[str],
    ) -> tuple[
        list[tuple[Path, ToolchainProfile, list[list[str]]]] | None,
        list[tuple[int, int]],
        dict[Path, list[str]],
        str,
    ]:
        """(the plan, where in the test figures each project's own tests are as (start,
        length), the unit's own test ids by project, why not): the plan is None when the
        profile cannot select."""
        try:
            touched = touched_tests(cwd, base)
        except (subprocess.CalledProcessError, OSError) as error:
            return None, [], {}, f"the unit's tests could not be listed ({error})"
        if projects:
            held = {where for where, _, _ in work}
            for name in incoming:
                owner = owning_project(projects, name)
                if (owner is None or cwd / owner.path not in held) and not is_doc_path(name):
                    return None, [], {}, f"{name} was brought in outside the unit's projects"
        plan: list[tuple[Path, ToolchainProfile, list[list[str]]]] = []
        owned: list[tuple[int, int]] = []
        own_ids: dict[Path, list[str]] = {}
        position = 0
        for where, toolchain, files in work:
            label = str(where.relative_to(cwd)) if where != cwd else "the repo"
            if not isinstance(toolchain, SelectsAffectedTests):
                return None, [], {}, f"the profile for {label} cannot select tests"
            here = [
                name[len(project.prefix) :]
                for name in incoming
                if (project := _owner(projects, where, cwd, name)) is not None
            ]
            selected = toolchain.affected_test_commands(
                where,
                [*files, *here],
                [],
                seed=selection_seed(where),
                root_extras=root_extras or [],
                **worker_settings,
            )
            if selected is None:
                hint = (
                    "" if affected is not None else "; checks.affected is off, so no data is kept"
                )
                return (
                    None,
                    [],
                    {},
                    f"the profile cannot say which tests {label} is affected in{hint}",
                )
            ids = ids_for(touched, cwd, where, toolchain)
            own_ids[where] = ids
            own = []
            if ids and isinstance(toolchain, RepeatsTests):
                for command in toolchain.test_commands(
                    where, files, root_extras=root_extras or [], **worker_settings
                ):
                    again = toolchain.repeat_command(command, ids)
                    if again is not None:
                        own.append(again)
            owned.append((position, len(own)))
            position += len(own) + len(selected)
            plan.append((where, toolchain, [toolchain.lint_command(base), *own, *selected]))
        return plan, owned, own_ids, ""

    def record_selected(
        figures: list[tuple[float, int]], outcome: str, earlier: tuple[float, int] | None
    ) -> None:
        """Write the ledger line of a selected run: the saving is the last full run's time
        less this one's, never below zero, and absent with no full run to compare with."""
        unit, change, node, round_number = spans.current_unit.get()
        seconds = sum(taken for taken, _ in figures)
        latest = last_full.get(unit)
        spans.record_affected(
            spans.AffectedRun(
                at=spans.clock.now().isoformat(),
                unit=unit,
                change=change,
                node=node,
                round=round_number,
                selected=sum(count for _, count in figures),
                total=latest[1] if latest else None,
                saved_seconds=max(0.0, earlier[0] - seconds) if earlier else None,
                outcome=outcome,
            ),
            log or (lambda message: None),
        )

    def full(
        cwd: Path,
        base: str,
        work: list[tuple[Path, ToolchainProfile, list[str]]],
        whole_repo: bool,
        *,
        lint: bool,
    ) -> tuple[bool, str]:
        """The unit's unit-test in full; its test time and count are kept, as what a later
        selected run is compared with."""
        figures: list[tuple[float, int]] = []
        try:
            return run_full(cwd, base, work, whole_repo, lint, figures)
        finally:
            if figures:
                last_full[spans.current_unit.get()[0]] = (
                    sum(taken for taken, _ in figures),
                    sum(count for _, count in figures),
                )

    def run_full(
        cwd: Path,
        base: str,
        work: list[tuple[Path, ToolchainProfile, list[str]]],
        whole_repo: bool,
        lint: bool,
        figures: list[tuple[float, int]],
    ) -> tuple[bool, str]:
        ran_tests: list[tuple[Path, ToolchainProfile, list[list[str]]]] = []
        for where, toolchain, files in work:
            if whole_repo:
                lint_command = toolchain.lint_command_all_files()
                test_commands = toolchain.test_commands_all(
                    where, root_extras=root_extras or [], **worker_settings
                )
            else:
                lint_command = toolchain.lint_command(base)
                test_commands = toolchain.test_commands(
                    where, files, root_extras=root_extras or [], **worker_settings
                )

            tests = len(test_commands)
            commands = [*([lint_command] if lint else []), *test_commands]
            for index, planned in enumerate(commands):
                is_test = index >= len(commands) - tests
                # A full run keeps the data a later selection reads, without selecting.
                command = (
                    toolchain.seeding_command(planned, selection_seed(where))
                    if is_test
                    and affected is not None
                    and not whole_repo
                    and isinstance(toolchain, RecordsSelectionData)
                    else planned
                )
                started = spans.clock.monotonic()
                before = begin_evidence(where, toolchain) if is_test else None
                result = ran(command, where, toolchain)
                if command is not planned and _tooling_lost(toolchain, command, result):
                    _say(
                        log,
                        f"affected tests: {_program(command)} could not use the selection "
                        "tooling, running the tests without it",
                    )
                    command = planned
                    result = ran(command, where, toolchain)
                if is_test:
                    figures.append((spans.clock.monotonic() - started, _counted(toolchain, result)))
                if not toolchain.tolerates_exit(command, result.returncode):
                    bundle = save_bundle(before, command, result, where, toolchain, base)
                    if isolate(
                        command,
                        result,
                        where,
                        toolchain,
                        log=log,
                        base=base,
                        evidence=(bundle, before) if bundle and before else None,
                    ):
                        continue
                    return False, _failure(command, result, where)
            ran_tests.append((where, toolchain, test_commands))
        passed, output = root_checks(cwd, ran_tests)
        if not passed or whole_repo:
            return passed, output
        return repeat(cwd, base, ran_tests)

    def begin_evidence(
        where: Path, toolchain: ToolchainProfile
    ) -> tuple[datetime, dict[str, object], dict[str, object]] | None:
        """The start of a test run's evidence: the time, the machine and the worktree. None when
        no bundles are kept."""
        if failures_dir is None:
            return None
        return (
            clock(),
            (machine or failure_evidence.machine_sample)(),
            failure_evidence.worktree_state(run, where, toolchain),
        )

    def save_bundle(
        before: tuple[datetime, dict[str, object], dict[str, object]] | None,
        command: list[str],
        result: subprocess.CompletedProcess,
        where: Path,
        toolchain: ToolchainProfile,
        base: str,
    ) -> Path | None:
        """Save the test run `before` began as a bundle, with its end sampled now, when it
        failed. Every place a test command is run calls this with what `begin_evidence` gave,
        so no failing run is missed; None (no bundles kept) or a run that passed saves nothing,
        and neither does a run whose failed tests are all ones this round already kept as a
        storm's evidence: the same failure of a second command adds no new evidence. Bundles
        a flake or storm record names are not pruned. Returns the bundle's folder, or None
        when nothing was saved."""
        if before is None or failures_dir is None:
            return None
        if toolchain.tolerates_exit(command, result.returncode):
            return None
        output = f"{result.stdout}\n{result.stderr}".strip()
        failed = failed_ids(toolchain, output)
        if failed and set(failed) <= stormed.get(spans.current_unit.get(), set()):
            # The same tests, already kept as a storm's evidence this round.
            return None
        started, machine_before, tree_before = before
        ended = clock()
        sampled = machine or failure_evidence.machine_sample
        unit, change, _, round_number = spans.current_unit.get()
        facts: dict[str, object] = {}
        if isinstance(toolchain, ReportsRunFacts):
            # The query runs as the test did, with the check configuration `ran` found for it.
            probe = toolchain.version_probe(
                located(toolchain, command, where, checkout.get("root", where))
            )
            facts = toolchain.run_facts(
                command, failure_evidence.probe_output(run, where, probe) if probe else ""
            )
        folder = temp_folder()
        temp = {"temp_run": run_token["id"], "temp_folder": folder} if folder else {}
        context: dict[str, object] = {
            "command": shlex.join(command),
            "started": started.isoformat(),
            "ended": ended.isoformat(),
            "seconds": (ended - started).total_seconds(),
            "unit": unit,
            "round": round_number,
            "tick": spans.PROCESS_TICK,
            "pid": os.getpid(),
            "cpus": os.cpu_count(),
            **temp,
            **failure_evidence.shas(run, where, base),
            **facts,
        }
        return write_failure_bundle(
            failures_dir,
            unit,
            change,
            started,
            output=output,
            context=context,
            machine={"start": machine_before, "end": sampled()},
            worktree=failure_evidence.worktree_changes(
                tree_before, failure_evidence.worktree_state(run, where, toolchain)
            ),
            pointed=_pointed_bundles(),
        )

    def root_checks(
        cwd: Path, ran_tests: list[tuple[Path, ToolchainProfile, list[list[str]]]] | None = None
    ) -> tuple[bool, str]:
        """The checks that are not a lint or a test run. The repo profile's look at the
        checkout as a whole and run once, in its root, whatever was touched; what is about
        one project is checked in it, by the project's own profile."""
        if repo is None:
            return True, ""
        for command in profile.extra_checks(repo):
            result = ran(command, cwd, profile)
            if not profile.tolerates_exit(command, result.returncode):
                return False, _failure(command, result)
        checked: set[tuple[Path, str]] = set()
        for where, toolchain, _ in ran_tests or []:
            if (where, toolchain.name) in checked or not isinstance(toolchain, ProjectChecks):
                continue
            checked.add((where, toolchain.name))
            for command in toolchain.project_checks(repo):
                result = ran(command, where, toolchain)
                if not toolchain.tolerates_exit(command, result.returncode):
                    return False, _failure(command, result, where)
        return True, ""

    def repeat(
        cwd: Path, base: str, ran_tests: list[tuple[Path, ToolchainProfile, list[list[str]]]]
    ) -> tuple[bool, str]:
        """Run the tests the unit added or changed again, under the load of the run that
        passed. A new test has no excuse to be flaky, so any failure fails unit-test."""
        runs = active().global_limits.unit_test_repeat_runs
        try:
            touched = touched_tests(cwd, base) if runs else []
        except (subprocess.CalledProcessError, OSError) as error:
            # What the unit touched cannot be read; the checks that ran stand.
            _say(log, f"repeat check skipped, the unit's tests could not be listed ({error})")
            return True, ""
        for where, toolchain, commands in ran_tests:
            if not isinstance(toolchain, RepeatsTests):
                continue
            # The profile selects by identifier, relative to where its command runs.
            # Only test files: a `test_*` method in a source file is not collected.
            ids = ids_for(touched, cwd, where, toolchain)
            for command in commands if ids else []:
                again = toolchain.repeat_command(command, ids)
                if again is None:
                    continue
                for _ in range(runs):
                    before = begin_evidence(where, toolchain)
                    result = ran(again, where, toolchain)
                    nothing = (
                        result.returncode != 0
                        and result.returncode == toolchain.no_tests_collected_exit
                    )
                    if nothing:
                        break
                    save_bundle(before, again, result, where, toolchain, base)
                    if not toolchain.tolerates_exit(again, result.returncode):
                        return False, _failure(again, result, where)
        return True, ""

    def selection(
        base: str,
        work: list[tuple[Path, ToolchainProfile, list[str]]],
        failed_output: str,
    ) -> list[tuple[Path, ToolchainProfile, list[list[str]]]] | None:
        """Per project, its lint and the tests the change affects; None when they cannot
        be named, so that the full suite stands in."""
        assert affected is not None
        plan = []
        for where, toolchain, files in work:
            # The identifiers are relative to the project whose command failed.
            named = (
                failed_ids(toolchain, failed_output)
                if len(work) == 1 or failed_in(where) in failed_output
                else []
            )
            if affected.mode == "command":
                tests = [expand_template(affected.command or "", files, named, **worker_settings)]
            else:
                tests = (
                    toolchain.affected_test_commands(
                        where,
                        files,
                        named,
                        seed=selection_seed(where),
                        root_extras=root_extras or [],
                        **worker_settings,
                    )
                    if isinstance(toolchain, SelectsAffectedTests)
                    else None
                )
            if tests is None:
                _say(log, "affected tests: the profile cannot say, running the full suite")
                return None
            plan.append((where, toolchain, [toolchain.lint_command(base), *tests]))
        return plan

    def run_selection(
        plan: list[tuple[Path, ToolchainProfile, list[list[str]]]],
        figures: list[tuple[float, int]],
        why: list[str] | None = None,
        own: dict[Path, list[str]] | None = None,
        flaked: list[Flake] | None = None,
        *,
        base: str = "",
    ) -> tuple[bool, str] | None:
        """(passed, what failed), or None when a command could not start, with the reason
        added to `why`. The time and test count of each selected test command are added to
        `figures`. A moved base's run gives `own`, the tests the unit added or changed in
        each project: a failure there is isolated as a scoped run's, and its flakes are
        added to `flaked` while the rest of the plan still runs."""
        for where, toolchain, commands in plan:
            for index, command in enumerate(commands):
                started = spans.clock.monotonic()
                before = begin_evidence(where, toolchain) if index > 0 else None
                try:
                    result = ran(command, where, toolchain)
                except OSError as error:
                    _say(
                        log,
                        f"affected tests: {_program(command)} could not run ({error}), "
                        "running the full suite",
                    )
                    if why is not None:
                        why.append(f"{_program(command)} could not run ({error})")
                    return None
                if index > 0 and (reason := _deactivated(toolchain, command, result)):
                    _say(
                        log,
                        f"affected tests: selection was deactivated ({reason}), "
                        "running the full suite",
                    )
                    if why is not None:
                        why.append(f"selection was deactivated ({reason})")
                    return None
                if index > 0 and _tooling_lost(toolchain, command, result):
                    _say(
                        log,
                        f"affected tests: {_program(command)} could not use the selection "
                        "tooling, running the full suite",
                    )
                    if why is not None:
                        why.append(f"{_program(command)} could not use the selection tooling")
                    return None
                if index > 0:
                    figures.append((spans.clock.monotonic() - started, _counted(toolchain, result)))
                # The first command is lint; a selector that picks nothing is a pass.
                nothing = index > 0 and result.returncode == toolchain.no_tests_collected_exit
                bundle = (
                    None
                    if nothing
                    else save_bundle(before, command, result, where, toolchain, base)
                )
                if not nothing and not toolchain.tolerates_exit(command, result.returncode):
                    try:
                        if index > 0 and isolate(
                            command,
                            result,
                            where,
                            toolchain,
                            log=log,
                            own=None if own is None else own.get(where, []),
                            evidence=(bundle, before) if bundle and before else None,
                        ):
                            continue
                    except FlakeFound as found:
                        if flaked is None:
                            raise
                        flaked.extend(found.flakes)
                        continue
                    return False, _failure(command, result, where)
        return True, ""

    def isolate(
        command: list[str],
        result: subprocess.CompletedProcess,
        where: Path,
        toolchain: ToolchainProfile,
        log: Callable[[str], None] | None = None,
        own: list[str] | None = None,
        base: str | None = None,
        evidence: tuple[Path, tuple[datetime, dict[str, object], dict[str, object]]] | None = None,
    ) -> bool:
        """Run the failed tests again, alone and serially, twice. Raises `FailedOnBase`, before
        any rerun, when an open change already fixes every one of the failed tests. Raises
        `FlakeFound` when they pass both times, marked scoped when `own` (the tests the unit
        added or changed, given by a moved base's run) is given, unless one of them is the
        unit's own, which is never excused: that is a failure. A test that fails alone is run
        on `base` (the unit's own, given by a full run) unless the unit wrote it:
        `FailedOnBase` when every one fails there too, and so does a failure of the time
        limit alone, which the base cannot tell apart. Returns False when any fails again, or the
        profile cannot say which tests failed, so the failure stands. Returns True when more than
        `global_limits.max_flakes_per_run` tests failed and passed both reruns: a disturbed run, not
        that many flaky tests, so it is recorded as one storm, no fix change is written, and the
        caller goes on to the checks that remain. With `evidence` (the failing run's bundle and
        how it began) each rerun is kept in the bundle, and the flakes and the storm name it with
        the conditions the reruns ran under."""
        rerun_command = getattr(toolchain, "serial_rerun_command", None)
        if rerun_command is None:
            return False
        output = f"{result.stdout}\n{result.stderr}".strip()
        stored = redact_text(output, where="unit-test output")
        tests = failed_ids(toolchain, output)
        if not tests:
            return False
        # Read from the redacted text, so what is kept of a section holds no secret.
        sections = _failure_sections(toolchain, stored)
        at = datetime.now(UTC)
        rerun_exits: list[int] = []
        rerun_seconds: list[float] = []
        last_sample: dict[str, object] = {}

        def evidenced() -> dict[str, Any]:
            """The bundle, when the first run started and the conditions the run and its reruns
            went under (the load before and after, each rerun's exit and seconds); empty without
            a bundle."""
            if evidence is None:
                return {}
            conditions: dict[str, object] = {}
            for key, sample in (("load_before", evidence[1][1]), ("load_after", last_sample)):
                load = sample.get("load")
                if isinstance(load, list) and load:
                    conditions[key] = load[0]
            conditions["rerun_exits"] = list(rerun_exits)
            conditions["rerun_seconds"] = list(rerun_seconds)
            return {
                "evidence": str(evidence[0]),
                "ran_at": evidence[1][0],
                "conditions": conditions,
            }

        def flakes_of(names: list[str], base_output: str = "") -> tuple[Flake, ...]:
            return tuple(
                Flake(
                    test=test,
                    command=shlex.join(command),
                    output=cut_tail(stored, 4000),
                    failure=cut_tail(sections.get(test, ""), FLAKE_FAILURE_CHARS),
                    at=at,
                    directory=str(where),
                    base=base or "",
                    base_output=base_output,
                    **evidenced(),
                )
                for test in names
            )

        covered = covered_tests(tests)
        if covered and len(covered) == len(tests):
            # Only when every failed test has a fix: one that has none is rerun and checked
            # on the base, so it is not lost behind the others.
            raise FailedOnBase(flakes_of(covered))
        if set(tests) <= stormed.get(spans.current_unit.get(), set()):
            # Another command of this round failed these same tests, which passed alone and were
            # recorded as a storm: they are not run again, nor recorded twice.
            return True
        rerun = rerun_command(command, tests)
        timed_out: list[str] = []
        timeouts = 0
        for number in range(1, FLAKE_RERUNS + 1):
            began = begin_evidence(where, toolchain) if evidence is not None else None
            again = ran(rerun, where, toolchain)
            if evidence is not None and began is not None:
                started, machine_before, tree_before = began
                ended = clock()
                last_sample.update((machine or failure_evidence.machine_sample)())
                seconds = (ended - started).total_seconds()
                rerun_exits.append(again.returncode)
                rerun_seconds.append(seconds)
                write_rerun_evidence(
                    evidence[0],
                    number,
                    output=f"{again.stdout}\n{again.stderr}".strip(),
                    context={
                        "command": shlex.join(rerun),
                        "exit": again.returncode,
                        "started": started.isoformat(),
                        "ended": ended.isoformat(),
                        "seconds": seconds,
                    },
                    machine={"start": machine_before, "end": dict(last_sample)},
                    worktree=failure_evidence.worktree_changes(
                        tree_before, failure_evidence.worktree_state(run, where, toolchain)
                    ),
                )
            if toolchain.tolerates_exit(rerun, again.returncode):
                continue
            again_output = f"{again.stdout}\n{again.stderr}"
            failed_again = failed_ids(toolchain, again_output)
            limit = getattr(toolchain, "time_limit_tests", lambda text: [])(again_output)
            if not failed_again or not set(failed_again) <= set(limit):
                if base is not None and not wrote(tests, where, base):
                    if (on_base := fails_on_base(rerun, tests, where, toolchain, base)) is not None:
                        raise FailedOnBase(flakes_of(tests, on_base))
                return False
            timed_out = failed_again
            timeouts += 1
        if timeouts:
            # By its time limit alone, every time: the base cannot tell it apart.
            if timeouts == FLAKE_RERUNS and base is not None and not wrote(timed_out, where, base):
                raise FailedOnBase(flakes_of(timed_out))
            return False
        if own is not None and any(test in own for test in tests):
            return False
        if len(tests) > active().global_limits.max_flakes_per_run:
            failures = [
                cut_tail(sections.get(test, ""), STORM_FAILURE_CHARS)
                for test in tests[:STORM_FAILURES]
            ]
            record_storm(
                spans.current_unit.get()[0], tests, shlex.join(command), failures, **evidenced()
            )
            stormed.setdefault(spans.current_unit.get(), set()).update(tests)
            _say(
                log,
                f"{len(tests)} tests failed the first pass and passed on the rerun; recorded "
                "as one storm, no fix changes" + "".join(f"\n{failure}" for failure in failures),
            )
            return True
        raise FlakeFound(flakes_of(tests), scoped=own is not None)

    def wrote(tests: list[str], where: Path, base: str) -> bool:
        """Whether the unit wrote any of `tests`: its file, or the `conftest.py` beside it,
        changed against `base`. True when that cannot be read, so the failure stays the unit's."""
        root = checkout["root"]
        try:
            files = set(changed(root, base))
        except (subprocess.CalledProcessError, OSError):
            return True
        for test in tests:
            path = where / test.partition("::")[0]
            shown = path.relative_to(root) if path.is_relative_to(root) else path
            if written_by_unit(shown, files):
                return True
        return False

    def fails_on_base(
        rerun: list[str], tests: list[str], where: Path, toolchain: ToolchainProfile, base: str
    ) -> str | None:
        """The output of the base run when every one of `tests` fails alone on `base`, in a clean
        worktree of it; None when one passes there. A base run that cannot be made proves
        nothing."""
        root = checkout["root"]
        try:
            with worktree_at(root, base) as tree:
                done = ran(rerun, tree / where.relative_to(root), toolchain, root=tree)
        except (subprocess.CalledProcessError, OSError, ValueError) as error:
            logger.warning("unit-test base run could not be made, so it proves nothing: %s", error)
            return None
        text = f"{done.stdout or ''}\n{done.stderr or ''}"
        if not all(test in failed_ids(toolchain, text) for test in tests):
            return None
        return redact_text(cut_tail(text.strip(), 4000), where="unit-test base output")

    def test_env(toolchain: ToolchainProfile) -> dict[str, dict[str, str]]:
        """The `env` argument for a command of `toolchain`: the profile's test environment for
        this run, made once; nothing for a profile that sets none."""
        if installation is None or not isinstance(toolchain, SetsTestEnvironment):
            return {}
        name = type(toolchain).__name__
        if name not in run_environments:
            unit = spans.current_unit.get()[0]
            run_environments[name] = toolchain.test_environment(installation, unit, run_token["id"])
            if folder := run_environments[name].get(TEMP_ROOT_VARIABLE):
                # The folder's name is the run's token alone: this line is how a unit is found
                # from a path in a failure.
                _say(log, f"temp folder {folder} (run {run_token['id']})")
        return {"env": {**os.environ, **run_environments[name]}}

    def temp_folder() -> str | None:
        """The temp folder this run's commands were given, when a profile gave one."""
        for given in run_environments.values():
            if TEMP_ROOT_VARIABLE in given:
                return given[TEMP_ROOT_VARIABLE]
        return None

    def ran(
        command: list[str], where: Path, toolchain: ToolchainProfile, root: Path | None = None
    ) -> subprocess.CompletedProcess:
        """Run `command` in `where`, spanned and logged; `root` is the checkout `where` is in
        when that is not the unit's (a worktree of its base)."""
        started = time.monotonic()
        mark = spans.Mark()
        outcome = "error"
        command = located(toolchain, command, where, root or checkout.get("root", where))
        if test_runs is not None and isinstance(toolchain, ReportsRunFacts):
            for key, value in toolchain.run_facts(command, "").items():
                run_facts.setdefault(key, value)
        try:
            result = run(command, cwd=where, **test_env(toolchain))
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
        if test_runs is not None and not ok:
            named = failed_ids(toolchain, f"{result.stdout or ''}\n{result.stderr or ''}")
            run_failed.extend(test for test in named if test not in run_failed)
        if log is not None:
            passed = "passed" if ok else f"exit {result.returncode}"
            seconds = time.monotonic() - started
            log(f"  unit-test: {' '.join(command)} (in {where}) {passed}, {seconds:.0f}s")
        return result

    return unit_test


def _first_load(sample: dict[str, object]) -> float | None:
    """The one-minute load average of a machine sample, when it has one."""
    load = sample.get("load")
    return float(load[0]) if isinstance(load, list) and load else None


def _running_units(installation: Installation | None) -> list[str]:
    """The ids of the units running now, from the store of `installation`; none without one."""
    if installation is None:
        return []
    try:
        stored = UnitStore(installation.state_dir / "units.json").all()
    except (OSError, ValueError):
        return []
    return [unit.id for unit in stored if unit.state == RUNNING]


def _active_installation() -> Installation | None:
    """The installation of the loaded workspace, or None when none is loaded."""
    root = active_root()
    return None if root is None else Installation(active(), root)


def _pointed_bundles() -> set[Path]:
    """The bundles the flake and storm rows name, which pruning keeps; none when no workspace
    is loaded."""
    installation = _active_installation()
    if installation is None:
        return set()
    record = flake_record(installation)
    return {Path(row.evidence) for row in [*record.entries(), *record.storms()] if row.evidence}


# What the evidence of a pre-existing failure starts with: the e2e-test split it failed in.
SPLIT_EVIDENCE = "e2e-test split: "


def build_on_flake(
    store: UnitStore,
    installation: Installation,
    *,
    runtime: AgentRuntime | None = None,
    run_openspec: openspec.Run | None = None,
    log: Callable[[str], None] = print,
) -> OnFlake:
    """Record a flake a unit met and make sure the one change that fixes it exists; with
    `wait` (the default) the unit waits on that change, without it, or for a unit of a fix
    change, no `Needs:` line is added. Returns that change, or None for a unit of the change
    itself, which has nothing to wait on."""

    def on_flake(unit: Unit, flake: Flake, *, wait: bool = True) -> str | None:
        met = flake.model_copy(update={"unit": unit.id})
        stored = store.get(unit.id)
        # A failure the base run shows was already failing there is a pre-existing one. One by its
        # time limit alone was never run on the base, and so is a test an open change already
        # covers (it is not rerun at all): both are recorded as regressions.
        kind = (
            FixKind.FLAKY
            if not flake.failing
            else FixKind.PRE_EXISTING
            if flake.base_output
            else FixKind.REGRESSION
        )
        row = met.model_copy(update={"fix_kind": kind.value})
        try:
            fix = wait_on_regression(
                installation,
                met,
                stored,
                kind=kind,
                runtime=runtime,
                base_output=flake.base_output,
                run_openspec=run_openspec,
                wait=wait,
                say=log,
            )
        except RegressionRunCapped:
            # Held back by the hour's cap: recorded without a change, which a later run links.
            flake_record(installation).append(row)
            raise
        flake_record(installation).append(row.model_copy(update={"change": fix or ""}))
        outcome = (
            "no wait" if not fix else f"waits for {fix}" if wait else f"recorded as {fix}, no wait"
        )
        log(f"{unit.id}: {'failing' if flake.failing else 'flaky'} test {flake.test} — {outcome}")
        return fix

    return on_flake


def build_on_preexisting(
    store: UnitStore,
    installation: Installation,
    *,
    runtime: AgentRuntime | None = None,
    run_openspec: openspec.Run | None = None,
    log: Callable[[str], None] = print,
) -> Callable[..., str | None]:
    """Record a test that failed on the base too and make sure one change fixes it; with
    `wait`, give each group of the unit a `Needs:` line on that change. Returns the
    change, or None for a unit of the change itself, which has nothing to wait on."""

    def on_preexisting(
        unit: Unit, verdict: E2eVerdict, failure: TestFailure, *, wait: bool
    ) -> str | None:
        split = failure.split or REST_SPLIT
        held = repo_holds(
            installation.config, installation.repo(unit.repo), installation.state_dir
        ).held
        if split == UNKNOWN_SPLIT or split in held:
            # A failure whose split is unknown is the unit's own, and a held
            # split's failure is nobody's bug: neither is recorded or fixed.
            return None
        met = PreExisting(
            test=failure.test,
            unit=unit.id,
            command=verdict.command,
            line=failure.line,
            at=datetime.now(UTC),
            base_output=verdict.base_output,
            split=split,
            evidence=verdict.evidence,
            ran_at=verdict.ran_at,
            conditions=verdict.conditions,
        )
        stored = store.get(unit.id)
        row = met.model_copy(update={"fix_kind": FixKind.PRE_EXISTING.value})
        try:
            fix = wait_on_regression(
                installation,
                Flake(
                    test=met.test,
                    unit=unit.id,
                    command=met.command,
                    output=met.line,
                    at=met.at,
                    evidence=f"{SPLIT_EVIDENCE}{split}\n{met.evidence}",
                    ran_at=met.ran_at,
                    conditions=met.conditions,
                    failing=True,
                    base=verdict.base,
                ),
                stored,
                kind=FixKind.PRE_EXISTING,
                runtime=runtime,
                base_output=met.base_output,
                run_openspec=run_openspec,
                wait=wait,
                say=log,
            )
        except RegressionRunCapped:
            # Held back by the hour's cap: recorded without a change, which a later run links.
            preexisting_record(installation).append(row)
            raise
        preexisting_record(installation).append(row.model_copy(update={"change": fix or ""}))
        log(f"{unit.id}: failing test {failure.test} — " + (f"fix {fix}" if fix else "no wait"))
        return fix

    return on_preexisting


def build_on_product_defect(
    store: UnitStore, installation: Installation, *, log: Callable[[str], None] = print
) -> Callable[[Unit, ProductDefect], str | None]:
    """Record a product defect a unit's builder reported and make sure one change fixes it;
    give each group of the unit a `Needs:` line on that change. Returns the change, or None
    for a unit of the change itself, which has nothing to wait on."""

    def on_product_defect(unit: Unit, defect: ProductDefect) -> str | None:
        fix = wait_on_product_defect(installation, defect, store.get(unit.id), say=log)
        product_defect_record(installation).append(
            ProductDefectEntry(
                test=defect.test,
                unit=unit.id,
                files=defect.files,
                reproduction=defect.reproduction,
                sketch=defect.sketch,
                at=datetime.now(UTC),
                change=fix or "",
            )
        )
        log(f"{unit.id}: product defect {defect.test} — " + (f"fix {fix}" if fix else "no wait"))
        return fix

    return on_product_defect


def ids_for(
    touched: list[tuple[str, str]], cwd: Path, where: Path, toolchain: ToolchainProfile
) -> list[str]:
    """The identifiers of the touched tests that fall under `where`, as a runner started
    there selects them. Only files the runner collects: a `test_*` method in a source file or a
    helper module is not."""
    return [
        f"{relative}::{name}"
        for path, name in touched
        if toolchain.collects_path(path) and (relative := _under(cwd / path, where)) is not None
    ]


def build_on_e2e_gate(
    store: UnitStore, installation: Installation, *, log: Callable[[str], None] = print
) -> Callable[..., list[str]]:
    """Give a unit about to run a full e2e-test run a `Needs:` line on each open fix change
    of a recorded base failure that holds it, and answer those changes (none: nothing
    holds it). `splits` are the splits the run executes (None: all). Writes no change."""

    def on_e2e_gate(unit: Unit, splits: Collection[str] | None = None) -> list[str]:
        stored = store.get(unit.id)
        held = [
            wait_on_change(
                installation, stored, entry.change, f"failing test {entry.test} on the base"
            )
            for entry in holding_fixes(installation, stored, store.all(), splits=splits)
        ]
        fixes = [fix for fix in held if fix]
        for fix in fixes:
            log(f"{unit.id}: open fix {fix} of a failing test on the base — waits")
        return fixes

    return on_e2e_gate


def _under(path: Path, where: Path) -> str | None:
    """`path` as seen from the directory `where`, or None when it is not inside it."""
    try:
        return path.relative_to(where).as_posix()
    except ValueError:
        return None


def _say(log: Callable[[str], None] | None, message: str) -> None:
    if log is not None:
        log(f"  unit-test: {message}")


def _owner(
    projects: list[ProjectConfig] | None, where: Path, cwd: Path, name: str
) -> ProjectConfig | None:
    """The project at `where` when it holds the file `name`, from the checkout's root; a
    repo with no projects is one at its root, whose project has no prefix."""
    if not projects:
        return ProjectConfig(path=".")
    project = owning_project(projects, name)
    return project if project is not None and cwd / project.path == where else None


def _program(command: list[str]) -> str:
    """The program a command runs, after the `VAR=value` words an `env` prefix sets."""
    words = iter(command)
    for word in words:
        if word != "env" and "=" not in word:
            return word
    return command[0]


def _tooling_lost(
    toolchain: ToolchainProfile, command: list[str], result: subprocess.CompletedProcess
) -> bool:
    """Whether a command made for the selection's data failed before running a test: no
    result line at all, so its tooling could not be had and the plain command is the answer.
    Collecting nothing is not that: pytest started, so the plugin loaded."""
    return (
        isinstance(toolchain, RecordsSelectionData)
        and toolchain.is_seeded(command)
        and result.returncode not in (0, toolchain.no_tests_collected_exit)
        and _counted(toolchain, result) == 0
    )


def _deactivated(
    toolchain: ToolchainProfile, command: list[str], result: subprocess.CompletedProcess
) -> str | None:
    """The reason a selected run's output gives for the selection being switched off, when the
    run ran tests: it selected nothing, so the full suite is the answer. A run that selected
    nothing for lack of a change prints no such line."""
    if not (
        isinstance(toolchain, RecordsSelectionData)
        and toolchain.is_seeded(command)
        and _counted(toolchain, result) > 0
    ):
        return None
    return toolchain.selection_deactivated(f"{result.stdout}\n{result.stderr}")


def _counted(toolchain: ToolchainProfile, result: subprocess.CompletedProcess) -> int:
    """How many tests a test run's output says it ran."""
    passed, failed, skipped, _ = toolchain.parse_test_summary(f"{result.stdout}\n{result.stderr}")
    return passed + failed + skipped


def _failure_sections(toolchain: ToolchainProfile, output: str) -> dict[str, str]:
    """Each failed test's own section of a failed check's output, as the profile reads them;
    none when it cannot."""
    reader = getattr(toolchain, "failure_sections", None)
    return reader(output) if reader is not None else {}


def expand_template(
    template: str,
    changed_files: list[str],
    failed_ids: list[str],
    *,
    workers: str | int = "auto",
    max_workers: int = 8,
) -> list[str]:
    """The argv a `command`-mode template stands for: each placeholder, a word of its
    own, becomes one argument per file or identifier, whatever characters they hold."""
    words = dict(
        zip(
            TEMPLATE_PLACEHOLDERS,
            (changed_files, failed_ids, worker_options(workers, max_workers)),
            strict=True,
        )
    )
    return [arg for word in shlex.split(template) for arg in words.get(word, [word])]


def _failure(
    command: list[str], result: subprocess.CompletedProcess, where: Path | None = None
) -> str:
    """The command that failed, then where it ran, then the tail of what it printed: a
    bare "unit-test failed" says nothing about which check or why, and the next fix round's
    selection needs to know which project's tests the identifiers belong to."""
    printed = redact_text(f"{result.stdout}\n{result.stderr}".strip(), where="unit-test output")
    printed = cut_tail(printed, 4000)
    header = f"$ {shlex.join(command)} (exit {result.returncode})"
    if where is not None:
        header += f"\n{failed_in(where)}"
    return f"{header}\n{printed}".strip()


def _work(
    cwd: Path,
    base: str,
    whole_repo: bool,
    projects: list[ProjectConfig] | None,
    profile: ToolchainProfile,
    changed: Callable[..., list[str]],
) -> list[tuple[Path, ToolchainProfile, list[str]]]:
    """Where to run unit-test, under which toolchain, over which files.

    One entry per project the unit touched, its files relative to that project
    - a profile's test commands name paths from the directory they run in.
    A repo with no projects declared is one entry at its root, which is what
    every installation written before projects existed still gets. A project whose
    directory is absent from `cwd` is pending and has no entry; where every declared
    project is pending there is nothing to run.
    """
    if not projects:
        return [(cwd, profile, [] if whole_repo else changed(cwd, base))]
    absent = {p.path for p in pending_projects(cwd, projects)}
    projects = [p for p in projects if p.path not in absent]
    if not projects:
        return []
    if whole_repo:
        return [(cwd / p.path, profiles.get(p.profile), []) for p in projects]

    work = [
        (cwd / project.path, profiles.get(project.profile), files)
        for project, files in by_project(projects, changed(cwd, base))
        if project is not None
    ]
    # Never the repo root. A repo that declares its projects is saying its root
    # is not one of them, and a linter run there finds no config and fails
    # outright: a unit whose only mistake was updating docs that live above the
    # project stopped on exactly that. The python profile's lint takes a ref range,
    # so each project's own run already sees every file in the diff, outside files
    # included; a profile may scope its lint to its project instead. Either way a
    # root run is no answer: it has no project config to run under.
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
        unit_id = unit_id_of_branch(store.all(), branch, active().git.branch_prefix)
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
) -> Callable[[str, E2eResult], None]:
    """Post an e2e-test result as a commit status on whichever host the repo lives on.

    `head` is the branch it belongs to, for a host that also shows it on the
    open pull request."""
    for_repo = for_repo or forges.for_repo

    def post(repo_name: str, result: E2eResult) -> None:
        forge, repo = for_repo(repo_name)
        e2e_post_status(forge, repo, result, head=head)

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
        # A unit whose first pull request merged is opening its late fix.
        merged_before = [p for p in _pulls_of(unit) if p.merged_at]
        title = (
            f"{unit.id}: late fix for #{merged_before[-1].number}"
            if merged_before
            else f"{unit.id}: {unit.title}"
        )

        stacking = store is not None and forge.supports_stacks
        below = _below(unit, base) if stacking else None
        expected = stacked_body is not None and below is not None and not _recorded_refusal(unit)
        chosen = stacked_body if expected and stacked_body is not None else body

        if number is None:
            number = forge.create_pr(repo, head=branch, base=base, title=title, body=chosen)
            fresh = True
        else:
            forge.update_pr(repo, number, base=base, body=chosen)
            fresh = False
        if merged_before:
            _list_late_fix(unit, number, branch)

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

    def _pulls_of(unit: Unit) -> tuple[Pull, ...]:
        return store.get(unit.id).pulls if store is not None else ()

    def _list_late_fix(unit: Unit, number: int, branch: str) -> None:
        listed = _pulls_of(unit)
        if store is None or any(p.number == number for p in listed):
            return
        late = Pull(number=number, branch=branch, role="late-fix", opened_at=spans.clock.now())
        store.set_pulls(unit.id, (*listed, late))

    def _record_size(unit: Unit, changes: list[FileChange]) -> None:
        """Record the size the reviewer sees now, and say so when it is over
        the ceiling. Bookkeeping: the caller never lets it stop the unit."""
        if not changes:
            return
        lines = actual_lines(changes)
        if store is not None:
            store.set_actual_lines(unit.id, lines)
        if over_ceiling(lines, unit):
            log(
                f"{unit.id}: estimated {unit.estimated_lines}, landed {lines}, "
                f"over the ceiling of {unit_ceiling(unit)}"
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

    # A resolver here is an agent call like the lane's: asked of the guard first.
    moves = build_stack_moves(store, installation, gated=True)

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
        options: dict[str, Any] = {"name": unit.repo}
        if allow_dirty:
            options["allow_dirty"] = True
        if locks := lock_paths(repo, repos[unit.repo]):
            options["locks"] = locks
        if artifacts := artifact_patterns(repo, repos[unit.repo]):
            options["artifacts"] = artifacts
        return prepare(repos[unit.repo], branch_name(unit), base, root, **options)

    return worktree


Reading = Callable[[], UsageReading | None]
Decide = Callable[[UsageReading | None], Decision]


def _guard_decision(
    usage: Reading | None,
    decide: Decide | None,
    start: Callable[[], Decision] | None,
    account: claude_account.Account | None = None,
) -> Callable[[], tuple[Decision, datetime | None]]:
    """One decision of the usage guard, and the reset time to fall back on when a refusal
    names no time of its own.

    By default the decision is `decide_start`'s, which asks the endpoint only when a fresh
    reading could change it; the reset is the one the decision carries. A caller with its
    own `start`, or its own `usage` and `decide`, is asked as it says.
    """
    if start is None and usage is None and decide is None:
        start = partial(decide_start, account=account)
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
    account: claude_account.Account | None = None,
) -> tuple[Callable[[], tuple[bool, str]], Callable[[], datetime | None]]:
    """`may_start` and `resume_at` for one gate, taking one decision between them.

    A gate asks whether a start is allowed and, when it is not, when to look
    again. Both answers come from the decision the first took, so a refusal is
    one decision of the guard and its reason and its deadline describe the same moment.
    """
    decided = _guard_decision(usage, decide, start, account)
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


class E2eRun(Frozen):
    """The commands one project's e2e-test runs, from the directory `where`."""

    where: Path
    commands: list[list[str]]


class E2eScope(Frozen):
    """What an e2e-test run executes. `runs` are the commands that run: `own` has only those that
    select the unit's tests (`ids`, relative to the checkout) and none means nothing to run,
    `full` has the whole marker's. `reason` is the line to log. `dev_stack` is set where the
    repo's dev stack script runs e2e-test instead of `runs`."""

    mode: E2eUnitScope
    runs: list[E2eRun] = []
    ids: list[str] = []
    reason: str = ""
    dev_stack: bool = False


def e2e_work(
    cwd: Path, projects: list[ProjectConfig], profile: ToolchainProfile, marker: str
) -> list[tuple[Path, ToolchainProfile, list[list[str]]]]:
    """Where a full e2e-test run goes in a checkout, under which toolchain, with which commands:
    one entry per declared project (the checkout itself when none is declared), the commands
    empty where the toolchain has none."""
    return [
        (where, toolchain, toolchain.e2e_commands(where, marker=marker))
        for where, toolchain, _ in _work(cwd, "", True, projects, profile, lambda *_: [])
    ]


def _skipped_reason(
    touched: list[tuple[str, str]], work: Sequence[tuple[Path, ToolchainProfile, Any]]
) -> str:
    """The skip line, followed by the touched test files the runner does not collect."""
    reason = "e2e-test skipped: no e2e test added or changed"
    left_out = sorted(
        {
            path
            for path, _ in touched
            if any(tc.is_test_path(path) for _, tc, _ in work)
            and not any(tc.collects_path(path) for _, tc, _ in work)
        }
    )
    return f"{reason}; not collected by the suite: {', '.join(left_out)}" if left_out else reason


def e2e_scope(
    cwd: Path,
    base: str | None,
    *,
    change: str,
    setting: E2eUnitScope,
    profile: ToolchainProfile,
    projects: list[ProjectConfig],
    marker: str,
    dev_stack: str | None,
) -> E2eScope:
    """The one decision of how much of e2e-test a unit runs, taken before the stack lock.

    The whole marker runs (`full`, the reason being the line to log) under the `full`
    setting and wherever the run cannot be narrowed safely; otherwise the runs are the
    commands that take the tests the unit added or changed, and none means there is nothing
    to run."""
    work = e2e_work(cwd, projects, profile, marker)

    def whole(why: str, dev_stack: bool = False) -> E2eScope:
        runs = [E2eRun(where=where, commands=commands) for where, _, commands in work if commands]
        return E2eScope(
            mode=E2eUnitScope.FULL,
            runs=runs,
            reason=f"e2e-test runs whole: {why}",
            dev_stack=dev_stack,
        )

    if dev_stack and (cwd / dev_stack).is_file():
        return whole("the repo's dev stack script runs it", dev_stack=True)
    if is_scheduled(change):
        return whole("a scheduled run is the whole suite")
    if setting is E2eUnitScope.FULL:
        return whole("e2e_unit_scope is full")
    for _, toolchain, _ in work:
        if not isinstance(toolchain, RepeatsTests):
            return whole(f"the {toolchain.name} profile cannot select tests by identifier")
    if base is None:
        return whole("there is no base to list the unit's tests against")
    try:
        touched = touched_tests(cwd, base)
    except (subprocess.CalledProcessError, OSError) as error:
        return whole(f"the unit's tests could not be listed ({error})")
    runs: list[E2eRun] = []
    ids: list[str] = []
    for where, toolchain, commands in work:
        if not isinstance(toolchain, RepeatsTests):
            continue
        here = ids_for(touched, cwd, where, toolchain)
        narrowed = [toolchain.repeat_command(c, here) for c in commands]
        if commands := [command for command in narrowed if command is not None]:
            runs.append(E2eRun(where=where, commands=commands))
            prefix = f"{where.relative_to(cwd).as_posix()}/" if where != cwd else ""
            ids += [f"{prefix}{id_}" for id_ in here]
    return E2eScope(
        mode=E2eUnitScope.OWN,
        runs=runs,
        ids=list(dict.fromkeys(ids)),
        reason="" if runs else _skipped_reason(touched, work),
    )


class E2eSession:
    """One unit's e2e-test run, and the status that follows it.

    The result is held between the two because they happen either side of the
    push: e2e-test has to pass before anything is published, and GitHub will not
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
        timeout: float | None = None,
        timeout_setting: str | None = None,
        log: Callable[[str], None] = print,
        under: Callable[[], Path] | None = None,
        profile: ToolchainProfile | None = None,
        marker: str = "local_stack",
        scope: E2eUnitScope = E2eUnitScope.OWN,
        dev_stack: str | None = "scripts/dev-stack.sh",
        stack_versions_command: list[str] | None = None,
        env: Mapping[str, str] | None = None,
        projects: list[ProjectConfig] | None = None,
        output_dir: Path | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        held: Collection[str] = (),
        only: str | None = None,
        splits: Collection[E2eSplit] = (),
        unavailable: Collection[str] = (),
        dimensions: Mapping[str, Mapping[str, E2eDimensionValue]] | None = None,
    ) -> None:
        self.unit = unit
        self._dimensions = dimensions or {}
        # What the last run was skipped for (`<dimension>=<value>` text); empty when it ran.
        self._skipped_for = ""
        self.verdict: E2eVerdict | None = None
        self._held = held
        self._unavailable = unavailable
        self._only = self._only_given = only
        self._splits = splits
        self._on_dev_stack = False
        self._projects = projects or []
        # `verify.env`: what the live-stack tests need, the same here as after
        # a merge. Without it a unit's e2e-test ran them with none of it, and a
        # test needing it failed at setup however the unit was built.
        self._test_env = {"env": {**os.environ, **env}} if env else {}
        # The checkout whose dev stack this one's attaches to, if any
        # (dev_stack_underneath).
        self._under = under
        self._profile = profile or profiles.get("python-uv")
        self._marker = marker
        self._scope = scope
        # The repo's dev stack script, with `up`, `test` and `down`: e2e-test
        # runs the unit's branch on it rather than on the live stack, which
        # runs the default branch. None means the repo has no dev stack.
        self._dev_stack = Path(dev_stack) if dev_stack else None
        self._stack_versions_command = stack_versions_command
        self.lock = lock
        self._run = run or _run
        self._sha = sha or _head_sha
        self._status = status or build_post_status(head=branch_name(unit))
        self._timeout = timeout
        self._timeout_setting = timeout_setting
        self._log = log
        self._output_dir = output_dir
        self._now = now
        self.result: E2eResult | None = None
        self._started: datetime | None = None
        self._output_file: Path | None = None
        self._withheld = False

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold the e2e-test lock as this unit: the wait is logged, and recorded as a span."""
        mark = spans.Mark()
        waited = False

        def waiting(message: str) -> None:
            nonlocal waited
            waited = True
            self._log(message)

        with stack_lock(
            self.lock,
            self._timeout,
            self._timeout_setting,
            holder=self.unit.id,
            on_wait=waiting,
            on_stale=self._log,
        ):
            if waited:
                spans.record_span(
                    mark,
                    self._log,
                    unit=self.unit.id,
                    change=self.unit.change,
                    waited=spans.E2E_LOCK,
                )
            yield

    def _keep(self, header: str, out: str) -> None:
        """Append one command's whole output to this run's file, redacted as a whole
        before it is written so a secret cannot be split across two writes."""
        if self._output_dir is None:
            return
        if self._started is None:
            self._started = self._now()
        text = redact_text(f"{header}\n{out}\n", where="e2e-test output file")
        if text == WITHHELD:
            self._withheld = True
            # The notice has no line break of its own: without one the next command's
            # chunk would run onto its line.
            text += "\n"
        self._output_file = append_e2e_output(self._output_dir, self.unit, self._started, text)

    def _kept(self) -> dict[str, Any]:
        """The result's fields for the file written so far, none when there is none."""
        if self._output_file is None:
            return {}
        return {"output_file": str(self._output_file), "output_withheld": self._withheld}

    def scope(self, *, cwd: Path, base: str | None = None) -> E2eScope:
        """How much of e2e-test a run on `cwd` against `base` executes: the one decision `run`
        acts on and the open-fix gate asks."""
        expression = self._expression()
        if expression is None:
            held = ", ".join(self._selection().left_out)
            return E2eScope(
                mode=E2eUnitScope.OWN,
                runs=[],
                reason=f"e2e-test runs nothing: every split is held ({held})",
            )
        return e2e_scope(
            cwd,
            base,
            change=self.unit.change,
            setting=self._scope,
            profile=self._profile,
            projects=self._projects,
            marker=expression,
            dev_stack=str(self._dev_stack) if self._dev_stack else None,
        )

    @property
    def _only_split(self) -> str | None:
        """The split this run is limited to; the older name of the untagged group is `rest`."""
        return REST_SPLIT if self._only == BASE_GROUP else self._only

    def splits(self) -> tuple[str, ...]:
        """The splits this run executes: the one it runs alone, or every declared split it
        does not leave out."""
        only = self._only_split
        if only is not None:
            return (only,)
        left_out = set(self._selection().left_out)
        return tuple(split.name for split in self._splits if split.name not in left_out)

    def _selection(self) -> E2eSelection:
        """What this run selects: the whole marker when nothing is left out or the profile
        cannot express a selection, else the repo's splits less the held ones (or the one
        that runs alone; the untagged group is `rest`)."""
        if (
            not self._held and self._only is None and not self._unavailable
        ) or selection_unavailable(self._profile, dev_stack_script=False, splits=self._splits):
            return E2eSelection(marker=self._marker)
        return build_selection(
            self._marker,
            self._splits,
            held=self._held,
            only=self._only_split,
            unavailable=self._unavailable,
        )

    def _expression(self) -> str | None:
        """The text the test runner takes for this run's selection; None when it selects
        nothing, every split being held."""
        selection = self._selection()
        if selection.empty:
            return None
        if isinstance(self._profile, AppliesE2eSelection):
            return self._profile.expression(self._marker, selection)
        return self._marker

    def _lister(self, toolchain: ToolchainProfile, where: Path) -> Callable[..., list[str] | None]:
        """`toolchain`'s listing of the tests a selection holds in a command run from
        `where`; None for a profile that cannot list them or a listing that fails."""

        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess:
            return self._run(argv, cwd=where, **self._test_env)

        def listed(
            command: list[str], selection: E2eSelection, among: list[str] | None = None
        ) -> list[str] | None:
            if not isinstance(toolchain, AppliesE2eSelection):
                return None
            return toolchain.list_tests(command, selection, run=run, among=among)

        return listed

    def _listed(
        self,
        scope: E2eScope,
        toolchains: Mapping[Path, ToolchainProfile],
        selection: E2eSelection,
    ) -> list[str] | None:
        """The tests `selection` holds in every command of the scope, found by listing without
        running; None when any command's listing fails."""
        found: list[str] = []
        for run in scope.runs:
            lister = self._lister(toolchains[run.where], run.where)
            for command in run.commands:
                ids = lister(command, selection)
                if ids is None:
                    return None
                found += ids
        return found

    def _unrunnable(self, scope: E2eScope, toolchains: Mapping[Path, ToolchainProfile]) -> str:
        """What the split this run is limited to needs, as `<dimension>=<value>` text, when it
        holds tests and every one carries the marker of an unavailable value; else empty. Only
        the values the split's own tests carry are named."""
        if self._only is None or not self._unavailable or not scope.runs:
            return ""

        def excluding(marker: str) -> E2eSelection:
            return build_selection(
                self._marker, self._splits, only=self._only, unavailable=[marker]
            )

        if self._selection().empty:
            return needs_text(
                self._dimensions, [m for m in self._unavailable if excluding(m).empty]
            )
        wanted = self._listed(
            scope, toolchains, build_selection(self._marker, self._splits, only=self._only)
        )
        if not wanted or self._listed(scope, toolchains, self._selection()) != []:
            return ""
        carried = [
            marker
            for marker in self._unavailable
            if (left := self._listed(scope, toolchains, excluding(marker))) is None
            or set(left) != set(wanted)
        ]
        return needs_text(self._dimensions, carried)

    def _park(
        self, scope: E2eScope, toolchains: Mapping[Path, ToolchainProfile]
    ) -> tuple[list[str], E2eScope]:
        """The held splits holding a test this run would have executed, found by listing
        without running, and the scope without its commands when the parked tests were all
        there was to run."""
        if self._only is not None or not self._held:
            return [], scope
        parked: list[str] = []
        for name in sorted(self._held):
            held = build_selection(
                self._marker, self._splits, only=name, unavailable=self._unavailable
            )
            found = self._listed(scope, toolchains, held)
            if found is None:
                self._log(f"e2e-test parked {name}: its tests could not be listed")
            if found is None or found:
                parked.append(name)
        if scope.mode is E2eUnitScope.OWN and parked:
            # What is left to run is what the run's own selection holds in each command; a
            # listing that fails keeps its command, since it does not say the command is empty.
            selection = self._selection()
            kept = [
                run
                for run in scope.runs
                if not selection.empty
                and any(
                    (ids := self._lister(toolchains[run.where], run.where)(command, selection))
                    is None
                    or ids
                    for command in run.commands
                )
            ]
            if not kept:
                scope = scope.model_copy(
                    update={
                        "runs": [],
                        "reason": f"e2e-test runs nothing: {', '.join(parked)} parked",
                    }
                )
        return parked, scope

    def _attribute(
        self,
        failures: list[TestFailure],
        named_by: Mapping[str, tuple[Path, ToolchainProfile, list[str]]],
        cwd: Path,
    ) -> list[TestFailure]:
        """`failures` each with its split, found by one listing of a command's failed
        tests under each declared split's selection; `unknown` where a listing could not say."""
        named = [split for split in self._splits if split.marker is not None]
        by_command: dict[tuple[Path, tuple[str, ...]], list[str]] = {}
        for test, (where, _, command) in named_by.items():
            by_command.setdefault((where, tuple(command)), []).append(test)
        groups: dict[str, str] = {}
        for (where, command), tests in by_command.items():
            lister = self._lister(named_by[tests[0]][1], where)
            # The listing runs from the project, so it names a test without the project.
            prefix = f"{where.relative_to(cwd).as_posix()}/" if where != cwd else ""
            bare = {test: test.removeprefix(prefix) for test in tests}
            sure = True
            for split in named:
                selection = build_selection(
                    self._marker, self._splits, only=split.name, unavailable=self._unavailable
                )
                ids = lister(list(command), selection, list(bare.values()))
                if ids is None:
                    sure = False
                    continue
                for test, short in bare.items():
                    if short in ids:
                        groups.setdefault(test, split.name)
            for test in tests:
                groups.setdefault(test, REST_SPLIT if sure else UNKNOWN_SPLIT)
        return [f.model_copy(update={"split": groups.get(f.test, UNKNOWN_SPLIT)}) for f in failures]

    def run(
        self, *, cwd: Path, base: str | None = None, only: str | None = None
    ) -> tuple[bool, str]:
        """Run e2e-test on `cwd`. `base` is the ref this run is against: with it, the failed
        tests of files the unit left alone are run once on it, and `verdict` says whose
        each is. Without it, or on the dev stack, nothing is classified. `only` limits the
        run to one group, as a resume of a parked one does; a group still held is
        parked again without running. The result names the group it was limited to."""
        self._only = self._only_given if only is None else only
        done = self._execute(cwd=cwd, base=base)
        if self._only is not None and self.result is not None:
            self.result = self.result.model_copy(update={"only": self._only})
        return done

    def _execute(self, *, cwd: Path, base: str | None) -> tuple[bool, str]:
        self.verdict = None
        self._on_dev_stack = False
        self._started = None
        self._output_file = None
        self._withheld = False
        if self._only is not None and self._only in self._held:
            self._log(f"e2e-test parked {self._only}: still held")
            self.result = E2eResult(
                sha=self._sha(cwd),
                passed=0,
                failed=0,
                skipped=0,
                duration_seconds=0.0,
                command="",
                output="",
                ran_no_tests=True,
                parked=[self._only],
            )
            return True, build_snapshot(self.result)
        scope = self.scope(cwd=cwd, base=base)
        if scope.mode is E2eUnitScope.FULL:
            self._log(scope.reason)
        left_out = ", ".join(sorted(self._held))
        why = (
            selection_unavailable(
                self._profile, dev_stack_script=scope.dev_stack, splits=self._splits
            )
            if left_out
            else None
        )
        if why:
            self._log(f"e2e-test cannot leave out {left_out}: {why}")
        if scope.dev_stack and self._dev_stack is not None:
            return self._run_on_dev_stack(cwd, self._dev_stack)
        toolchains = {
            where: toolchain
            for where, toolchain, _ in _work(
                cwd, "", True, self._projects, self._profile, lambda *_: []
            )
        }
        parked, scope = self._park(scope, toolchains) if left_out and not why else ([], scope)
        self._skipped_for = ""
        if not scope.dev_stack and (needs := self._unrunnable(scope, toolchains)):
            self._log(f"e2e-test skipped {self._only}: nothing runnable: needs {needs}")
            self._skipped_for = needs
            self.result = E2eResult(
                sha=self._sha(cwd),
                passed=0,
                failed=0,
                skipped=0,
                duration_seconds=0.0,
                command="",
                output="",
                ran_no_tests=True,
                parked=parked,
            )
            return True, build_snapshot(self.result)
        if scope.mode is E2eUnitScope.OWN and not scope.runs:
            self._log(scope.reason)
            self.result = E2eResult(
                sha=self._sha(cwd),
                passed=0,
                failed=0,
                skipped=0,
                duration_seconds=0.0,
                command="",
                output="",
                ran_no_tests=True,
                parked=parked,
            )
            return True, build_snapshot(self.result)
        # The same entries unit-test resolves, over the whole repo: e2e-test has no
        # changed files to narrow to, and a project's `testpaths` decide what
        # pytest collects only when it runs from that project's directory.
        for project in pending_projects(cwd, self._projects):
            self._log(describe(project))
        entries = [(run.where, toolchains[run.where], run.commands) for run in scope.runs]
        sha = self._sha(cwd)
        passed = failed = skipped = 0
        duration = 0.0
        timed: list[TestTime] = []

        def labelled(project: str, test: str) -> str:
            """A test's id as the result names it: with its project, where there is one."""
            return f"{project}/{test}" if project else test

        # header, text, whether the command failed, the toolchain that read it, its project,
        # and where and with which command it ran
        outputs: list[tuple[str, str, bool, ToolchainProfile, str, Path, list[str]]] = []

        # A queue, not a fail-fast lock: a second unit's e2e tests are
        # perfectly valid, there is simply one local stack to run them on.
        with self._locked():
            for where, toolchain, commands in entries:
                # A project's output is labelled with it; a repo with no
                # projects has nothing to say about where.
                project = str(where.relative_to(cwd)) if where != cwd else ""
                label = f" (in {project})" if project else ""
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
                    timed += [
                        e.model_copy(update={"test": labelled(project, e.test)})
                        for e in with_split(toolchain.parse_test_durations(out), out)
                    ]
                    header = f"$ {' '.join(command)}{label}"
                    self._keep(header, out)
                    # The listing carries the durations, so the kept text leaves them out: they
                    # would fill the cut output and push the failures from it.
                    kept = toolchain.without_durations(out)
                    if f or completed.returncode not in (0, nothing):
                        outputs.append((header, kept, True, toolchain, project, where, command))
                    elif p:
                        outputs.append((header, kept, False, toolchain, project, where, command))

            # Every command's text in one pass, before any cut, so a cut cannot leave half a
            # value and a failing redaction is logged once.
            redacted = redact_leaves([out for _, out, *_ in outputs], where="e2e-test output")
            failures_count = sum(failed for _, _, failed, *_ in outputs)
            output = fit(
                [
                    _command_section(
                        header, text, toolchain, failed=failed, failures=max(failures_count, 1)
                    )
                    for (header, _, failed, toolchain, *_), text in zip(
                        outputs, redacted, strict=True
                    )
                ],
                E2E_OUTPUT_CHARS,
            )
            # Read from the redacted text, so a line is redacted before it is shortened.
            failures: list[TestFailure] = []
            # Which command named each failure, for the base run to repeat that one.
            named_by: dict[str, tuple[Path, ToolchainProfile, list[str]]] = {}
            for (_, _, command_failed, toolchain, project, at, ran), text in zip(
                outputs, redacted, strict=True
            ):
                if not command_failed:
                    continue
                for found in toolchain.parse_test_failures(text):
                    test = labelled(project, found.test)
                    failures.append(TestFailure(test=test, line=found.line))
                    named_by[test] = (at, toolchain, ran)
            failures = self._attribute(failures, named_by, cwd)
            # A test id is output too, and is redacted as the failures' ids are before it is
            # posted, stored or recorded.
            ids = redact_leaves([e.test for e in timed], where="e2e-test output")
            timed = [
                e.model_copy(update={"test": test}) for e, test in zip(timed, ids, strict=True)
            ]
            command = " && ".join(
                " ".join(c) + (f" (in {where.relative_to(cwd)})" if where != cwd else "")
                for where, _, commands in entries
                for c in commands
            )

            self.result = E2eResult(
                sha=sha,
                passed=passed,
                failed=failed,
                skipped=skipped,
                duration_seconds=duration,
                command=command,
                output=output,
                stack_versions=_stack_versions(self._stack_versions_command, run=self._run),
                failures=failures,
                durations=sorted(timed, key=lambda e: e.seconds, reverse=True),
                # An own run whose selected tests the marker leaves out collected nothing.
                ran_no_tests=scope.mode is E2eUnitScope.OWN and not (passed or failed or skipped),
                parked=parked,
                **self._kept(),
            )
            record_test_times(
                self.result.durations,
                unit=self.unit.id,
                change=self.unit.change,
                marker=self._marker,
            )

            # Still inside the hold: the base run sees the stack the unit's run saw.
            self.verdict = self._judge(cwd, base, named_by)
        return self.result.ok, build_snapshot(self.result)

    def passed_note(self) -> str:
        """The note of a scheduled unit whose whole run passed."""
        result = self.result
        assert result is not None, "e2e-test has not run for this unit"
        of = f" for {self._only}" if self._only else ""
        if self._skipped_for:
            return f"scheduled e2e-test skipped{of}: nothing runnable: needs {self._skipped_for}"
        return (
            f"scheduled e2e-test passed{of}: {result.passed} passed, {result.skipped} skipped "
            f"on {result.sha}"
        )

    def classify(self, *, cwd: Path, base: str | None) -> E2eClassification:
        """The failed tests of the last run, the unit's own and the untouched.

        A test is the unit's own when its file is one the branch changed against its base,
        or sits beside a `conftest.py` it changed. Nothing is classified when the run
        named no tests, ran on the dev stack, or there is no base to compare with.
        """
        if self.result is None or base is None or self._on_dev_stack:
            return E2eClassification()
        changed = set(changed_files(cwd, base))
        own: list[TestFailure] = []
        untouched: list[TestFailure] = []
        for failure in self.result.failures:
            is_own = failure.split == UNKNOWN_SPLIT or written_by_unit(
                Path(failure.test.partition("::")[0]), changed
            )
            (own if is_own else untouched).append(failure)
        return E2eClassification(own=own, untouched=untouched)

    def _judge(
        self,
        cwd: Path,
        base: str | None,
        named_by: dict[str, tuple[Path, ToolchainProfile, list[str]]],
    ) -> E2eVerdict | None:
        """Run the untouched failed tests once on the base and say whose each is.

        Each failed command is repeated on the base with only its own untouched ids.
        Pre-existing only when a base run itself names the test as failed or errored; a
        test it passes, does not contain or does not name is the unit's to fix. A base run
        that cannot be made (no worktree, a command that cannot start) proves nothing, so
        every test not yet named there is the unit's, and the unit fails as it would
        without the base run.
        """
        if self.result is not None and is_scheduled(self.unit.change):
            return self._scheduled_verdict()
        if (
            self.result is None
            or base is None
            or self.result.ok
            or not active().global_limits.e2e_base_runs
        ):
            return None
        classified = self.classify(cwd=cwd, base=base)
        if not classified.untouched:
            return None
        by_command: dict[tuple[Path, tuple[str, ...]], list[str]] = {}
        for failure in classified.untouched:
            at, _, ran = named_by[failure.test]
            by_command.setdefault((at, tuple(ran)), []).append(failure.test)
        failing: set[str] = set()
        commands: list[str] = []
        outputs: list[str] = []
        try:
            with worktree_at(cwd, base) as tree:
                for (at, ran), tests in by_command.items():
                    toolchain = named_by[tests[0]][1]
                    rerun = getattr(toolchain, "serial_rerun_command", None)
                    if rerun is None:
                        continue
                    project = str(at.relative_to(cwd)) if at != cwd else ""
                    prefix = f"{project}/" if project else ""
                    command = rerun(list(ran), [t.removeprefix(prefix) for t in tests])
                    completed = self._run(command, cwd=tree / at.relative_to(cwd), **self._test_env)
                    text = f"{completed.stdout or ''}{completed.stderr or ''}"
                    commands.append(" ".join(command))
                    # Covers a toolchain whose rerun keeps its flags, and so prints durations.
                    outputs.append(toolchain.without_durations(text))
                    named = toolchain.parse_test_failures(text)
                    failing.update(f"{prefix}{found.test}" for found in named)
        except (subprocess.CalledProcessError, OSError) as error:
            logger.warning("e2e-test base run could not be made, so it proves nothing: %s", error)
        return E2eVerdict(
            own=classified.own,
            broken=[f for f in classified.untouched if f.test not in failing],
            pre_existing=[f for f in classified.untouched if f.test in failing],
            command="; ".join(commands),
            base=base,
            base_output=redact_text(
                cut_tail("\n".join(outputs), 4000), where="e2e-test base output"
            ),
        )

    def _scheduled_verdict(self) -> E2eVerdict | None:
        """Every failure of a scheduled unit's run is pre-existing: its tree is its base, so a
        base run would be the same tree, command and stack. None when the run passed, base
        runs are off or no failure is named."""
        if self.result is None or self.result.ok or not active().global_limits.e2e_base_runs:
            return None
        if not self.result.failures:
            return None
        return E2eVerdict(
            pre_existing=list(self.result.failures),
            command=self.result.command,
            base_output=self.result.output,
        )

    def _run_on_dev_stack(self, cwd: Path, script: Path) -> tuple[bool, str]:
        """Deploy this branch onto the dev stack, test against it, take it down.

        The live stack runs the default branch, so a unit that changes
        deployment config — a published port, a gateway registration — can
        only pass e2e-test against a stack running its own branch. The dev stack
        is that, and cannot touch the live one. It is torn down whatever
        happens, so the next unit starts from its own branch.
        """
        self._on_dev_stack = True
        sha = self._sha(cwd)
        up = [str(script), "up"]
        test = [str(script), "test"]
        down = [str(script), "down"]
        with self._locked():
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
        self._keep(f"$ {' '.join(command)}", output)
        passed, failed, skipped, duration = self._profile.parse_test_summary(output)
        output = redact_text(output, where="e2e-test output")
        failures = self._profile.parse_test_failures(output)
        if completed.returncode and not failed:
            failed = 1
        self.result = E2eResult(
            sha=sha,
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_seconds=duration,
            command=f"{script} up && {script} test (then down)"
            if command == test
            else f"{script} up (failed)",
            output=cut_tail(output, 4000),
            stack_versions=_stack_versions(self._stack_versions_command, run=self._run),
            failures=failures,
            **self._kept(),
        )
        if is_scheduled(self.unit.change):
            self.verdict = self._scheduled_verdict()
        return self.result.ok, build_snapshot(self.result)

    def post(self, sha: str, ok: bool) -> None:
        if self.result is None:
            raise ValueError("e2e-test has not run for this unit, so there is no status to post")
        if sha != self.result.sha:
            raise ValueError(
                f"asked to post a status for {sha[:7]}, but e2e-test ran against a "
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
    """What the live stack was when e2e-test ran, so the claim can be checked:
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


def own_work_starts_after(
    tree: Path, base: str, unit: Unit, store: UnitStore, *, head: str = "HEAD"
) -> str:
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

    `head` names the branch when `tree` is not checked out on it.
    """
    start = git(tree, "merge-base", base, head, check=False).stdout.strip()
    known = list(store.all())
    index = {u.id: u for u in known}
    for dep in through_satisfied(unit, known):
        parent = index.get(dep)
        if parent is None or parent.repo != unit.repo:
            continue
        for ref in (parent.branch, parent.pushed, parent.approved):
            if not ref:
                continue
            fork = git(tree, "merge-base", ref, head, check=False).stdout.strip()
            # Later than what we have, and on this branch's own line.
            if fork and (not start or is_ancestor(tree, start, fork)):
                start = fork
                break
    return start


def _move_without_resolver(
    repo: Path,
    branch: str,
    *,
    new_base: str,
    old_base: str,
    turn: Turn = nullcontext,
    **_intent: str,
) -> Moved:
    """`move_branch_onto` with no resolver: a conflict is aborted and raised."""
    return move_branch_onto(repo, branch, new_base=new_base, old_base=old_base, turn=turn)


def build_restack_onto(
    store: UnitStore,
    *,
    move: Callable[..., Moved] | None = None,
    repo: RepoConfig | None = None,
    turn: Turn = nullcontext,
):
    """Move a resuming unit's branch onto its base, if the base has moved.

    Reuses `move_branch_onto` — the primitive, with its LLM conflict resolution
    and its check that the resolution did not simply delete one side — rather
    than `events.build_restack`, which also pushes, retargets the PR and
    comments. A resuming unit is not ready to push: it still has a review loop
    and unit-test ahead of it.

    "Has the base moved" is whether the base's tip is still an ancestor of this
    branch. If it is, nothing to do — and a rebase would be actively harmful,
    since it rewrites every commit and invalidates any check already run.

    `resolve=False` moves without the conflict resolver, for the check before a
    push: a conflict is aborted, the branch left at its head, and reported as
    `Restacked.conflict`, so the run goes back to its restack, where the resolution
    happens under the usage gate and with review told of it. A `resolver` is what
    the resolution asks instead of the one `resolved_move` makes.
    """
    resolving = move or partial(resolved_move, repo_config=repo)

    def restack_onto(
        *,
        tree: Path,
        branch: str,
        base: str,
        unit: Unit,
        resolve: bool = True,
        resolver: Resolver | None = None,
    ) -> Restacked | None:
        move = resolving if resolve else _move_without_resolver
        if is_ancestor(tree, base):
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
        # The caller's own resolver: a call of the unit's session, where it has one.
        asking: dict[str, Any] = {"resolve": resolver} if resolver and resolve else {}
        try:
            moved = retried_once(
                lambda: move(
                    tree,
                    branch,
                    new_base=base,
                    old_base=old_base,
                    moving_unit=unit.id,
                    moving_change=unit.change,
                    moving_repo=unit.repo,
                    moving_intent=unit.title,
                    onto_unit=onto_unit,
                    onto_intent=onto_intent,
                    turn=turn,
                    **asking,
                )
            )
        except RestackConflict as error:
            # Not a failure: what the resolver's steps could not settle goes to the adapt
            # step, which ports the work by hand. It needs
            # to know which tests the previous work had, to account for each.
            return Restacked(
                onto_unit=onto_unit,
                onto_intent=onto_intent,
                old_base=old_base,
                old_head=old_head,
                conflict=str(error),
                old_tests=tuple(defined_tests_in_range(tree, old_base, old_head)),
                tried=error.tried,
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
    is the trunk because the parent merged — the same-repo parent it depends on that comes
    last in plan order, whatever order the dependencies are listed in."""
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
    order = {u.id: place for place, u in enumerate(units)}
    return max(parents, key=lambda parent: order[parent.id]) if parents else None


def moving_onto(unit: StoredUnit, base: str, store: UnitStore) -> StoredUnit:
    """What a unit's move onto `base` is told it moves onto: the unit it is built on, or else
    a stand-in named for the base, so the resolver never hears of a unit moving onto itself."""
    return predecessor(unit, base, store) or unit.model_copy(update={"id": base, "title": base})


def _test_bodies(source: str, *, qualified: bool = False) -> dict[str, list[str]]:
    """Each `test_*` function's own source text, by name, decorators included.

    Body against body, not the file's diff: a test moved or resurrounded by
    unrelated edits should not read as changed, but one whose assertions,
    markers or parametrized cases actually shifted must — even kept under its
    old name. Every same-named test is kept (in different classes, say), so a
    change to any of them shows. A test moved into a class reads as changed,
    the safe direction. `qualified` names a method by its classes too
    (`Group::test_x`), which is how a runner selects it.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines()
    bodies: dict[str, list[str]] = {}

    def visit(node: ast.AST, classes: tuple[str, ...]) -> None:
        if qualified and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return  # nothing inside a function is collected by name; a function in it is no test id
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and child.name.startswith(
                "test_"
            ):
                first = min([d.lineno for d in child.decorator_list] + [child.lineno])
                end = child.end_lineno or child.lineno
                name = "::".join([*classes, child.name]) if qualified else child.name
                bodies.setdefault(name, []).append("\n".join(lines[first - 1 : end]))
            visit(child, (*classes, child.name) if isinstance(child, ast.ClassDef) else classes)

    visit(tree, ())
    return {name: sorted(texts) for name, texts in bodies.items()}


def _changed_tests(
    tree: Path, ref: str, *, qualified: bool, head: str | None = None
) -> list[tuple[str, str, bool]]:
    """(file, test, still there) for each test whose body differs between `ref` and the tree,
    or between `ref` and the commit `head` when one is given.

    Compared file by file in both directions, so a test that only survived the
    replay by name — kept, but silently weakened — is caught, and so is one
    gone from the file it was in, even when the same name lives on in another
    file or in a string.
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
        *([head] if head else []),
        "--",
        "*.py",
        errors="surrogateescape",
    )
    new = (
        git(
            tree,
            "ls-files",
            "-z",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
            errors="surrogateescape",
        ).stdout
        if head is None
        else ""
    )
    paths = {p for p in (diff.stdout + "\0" + new).split("\0") if p}
    changed: list[tuple[str, str, bool]] = []
    for path in sorted(paths):
        if head is None:
            file = tree / path
            source = file.read_text(errors="replace") if file.is_file() else ""
            present = file.is_file()
        else:
            shown = git(tree, "show", f"{head}:{path}", check=False, errors="replace")
            source, present = shown.stdout, shown.returncode == 0
        current = _test_bodies(source, qualified=qualified) if present else {}
        old_source = git(tree, "show", f"{ref}:{path}", check=False, errors="replace")
        old = (
            _test_bodies(old_source.stdout, qualified=qualified)
            if old_source.returncode == 0
            else {}
        )
        changed += [
            (path, n, n in current)
            for n in sorted(old.keys() | current.keys())
            if old.get(n) != current.get(n)
        ]
    return changed


def tests_changed(tree: Path, ref: str) -> set[str]:
    """Test functions whose body differs between `ref` and the tree, per file.

    A test moved to another file unchanged reads as changed. Data living
    outside the function, such as a module-level table a parametrize reads, is
    not seen.
    """
    return {name for _, name, _ in _changed_tests(tree, ref, qualified=False)}


def touched_tests(tree: Path, ref: str, head: str | None = None) -> list[tuple[str, str]]:
    """(file, test) for each test the tree adds or changes against `ref` (or the commit
    `head` adds or changes against it), as a runner selects it: the file's path from the
    tree's root and the test's name, with its classes (`Group::test_x`). A deleted test is
    not listed, since nothing is left to run."""
    return [(p, n) for p, n, there in _changed_tests(tree, ref, qualified=True, head=head) if there]


def own_test_ids(
    tree: Path,
    ref: str,
    work: Sequence[tuple[Path, ToolchainProfile, Any]],
    *,
    head: str | None = None,
) -> list[str]:
    """The identifiers, from the tree's root, of the tests a unit adds or changes against
    `ref` (up to `head`): the definition the e2e-test run narrows to, for one that wants the
    unit's own tests without running them. `work` is `e2e_work`'s."""
    touched = touched_tests(tree, ref, head)
    ids: list[str] = []
    for where, toolchain, _ in work:
        prefix = f"{where.relative_to(tree).as_posix()}/" if where != tree else ""
        ids += [f"{prefix}{id_}" for id_ in ids_for(touched, tree, where, toolchain)]
    return list(dict.fromkeys(ids))


def reset_to(tree: Path, onto: str, keep: str) -> None:
    """Keep the current work under `keep`, then put the branch on `onto`.

    A ref rather than a branch: it is there for the adapt step to read from,
    not to be built on or pushed, and a branch would clutter the checkout.
    """
    git(tree, "update-ref", keep, "HEAD")
    git(tree, "reset", "--hard", "-q", onto)


def build_move_empty_branch(
    *, turn: Turn = nullcontext
) -> Callable[[Path, str], tuple[str, str] | None]:
    """Fast-forward a branch with no commits of its own onto `ref`, in the repo's turn.

    Gives the old and the new tip, or None when the branch is already at `ref` or holds commits
    of its own. Uncommitted changes of the unit's own are carried; a move that would overwrite
    one is refused and moves nothing.
    """

    def move(tree: Path, ref: str) -> tuple[str, str] | None:
        with turn():
            old = git_out(tree, "rev-parse", "HEAD")
            new = tip(tree, ref)
            if not new or new == old or not is_ancestor(tree, old, new):
                return None
            moved = git(tree, "merge", "--ff-only", "-q", new, check=False)
            if moved.returncode:
                text = (moved.stderr or moved.stdout).strip()
                files = tuple(
                    line.strip() for line in text.splitlines() if line.startswith(("\t", " "))
                )
                raise EmptyBranchBlocked(files, text or f"git merge exited {moved.returncode}")
        return old, new

    return move


def is_ancestor(tree: Path, base: str, of: str = "HEAD") -> bool:
    """Whether `of` holds `base`: the one read of 'this branch already has its base'."""
    return not git(tree, "merge-base", "--is-ancestor", base, of, check=False).returncode


def build_upstream_incomplete(
    store: UnitStore, bounce_limit: int | None = None
) -> Callable[..., tuple[Cause, str] | None]:
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
        stored = as_stored(unit, known)
        for dep in followed_dependencies(stored, known):
            parent = index.get(dep)
            if (
                parent
                and parent.repo == unit.repo
                and parent.state not in BUILDS_NOTHING
                and parent.state not in REVIEWED
            ):
                note = f"{dep} is {parent.state} — it went back after this unit started"
                mine = index.get(unit.id)
                if (
                    bounce_limit is not None
                    and mine is not None
                    and mine.bounce_cause is Cause.UPSTREAM_WENT_BACK
                    and mine.bounces + 1 >= bounce_limit
                ):
                    note += f"; held repeatedly by {dep}"
                return (Cause.UPSTREAM_WENT_BACK, note)
        return None

    return upstream_incomplete


def why_branch_is_changing(
    parent: StoredUnit, graph: list[StoredUnit], head: Callable[[StoredUnit], str]
) -> str:
    """Why a predecessor's branch is changing, or an empty string when it isn't.

    A predecessor in review, merged or satisfied is settled. Otherwise it is
    changing when its branch holds a commit beyond its last pushed head, when it
    is rebasing (its history is being rewritten before a new head exists), or
    when it is itself planned for a changing upstream or a moved base.
    """
    if parent.state in REVIEWED or parent.state in BUILDS_NOTHING:
        return ""
    # A replan carries a standing cause, so these readings hold over it.
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
    deliver: Callable[[StoredUnit, str], bool] | None = None,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Set each unit in review back to planned while a same-repo predecessor's
    branch is changing; returns the ids moved.

    `head` reads a unit's branch head ("" when it has none).
    `why_branch_is_changing` says when a branch is changing. `deliver` hands the
    move to the unit's thread as an event, under its own branch claim, and says
    whether there was a thread to take it; without a thread, or without
    `deliver`, the move is written to the store under `claim`. Repeats until
    nothing moves, so a chain of dependents goes back in one pass. A unit with a
    deferred restack or a restack conflict is skipped while that cause stands,
    and one whose branch is busy is left for the next pass.
    """
    moved: list[str] = []
    progressed = True
    while progressed:
        progressed = False
        graph = list(store.all())
        index = {u.id: u for u in graph}
        for unit in graph:
            # A unit is moved once a pass: a delivery that leaves it in review (its thread
            # declined) must not be asked again, or the pass would never settle. The cause is
            # standing, so a replan carries it, and a deferred conflict move records it explicitly.
            if (
                unit.id in moved
                or unit.state != IN_REVIEW
                or unit.cause in (Cause.RESTACK_DEFERRED, Cause.RESTACK_CONFLICT)
            ):
                continue
            found = None
            for dep in followed_dependencies(unit, graph):
                parent = index.get(dep)
                if not parent or parent.repo != unit.repo:
                    continue
                if why := why_branch_is_changing(parent, graph, head):
                    found = (parent, why)
                    break
            if found is None:
                continue
            parent, why = found
            note = f"{parent.id} is changing: {why}"
            try:
                if deliver is None or not deliver(unit, note):
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


def as_stored(unit: Unit, known: Sequence[Unit]) -> Unit:
    """The unit as the store has it now, else as the run started with it: a `Needs:`
    line linked since the run began is a dependency of the unit it is running as."""
    return next((u for u in known if u.id == unit.id), unit)


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
        known = store.all()
        now = base_of(as_stored(unit, known), known)
        if now != base:
            return Cause.BASE_CHANGED, f"its base moved from {base} to {now} while it built"
        # Advanced is fine — a parent's rework adds on top, and the review or
        # the resume's restack takes it in. Rewritten is not.
        if start and not is_ancestor(tree, start, local_ref(base, repo=unit.repo)):
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
    (`consumes`, in abk.yaml), so its e2e-test runs on top of it — from the
    default branch as the remote has it (fetch_all runs every tick), never
    the user's own checkout.
    """
    base = installation.dev_stack_base(unit.repo)
    if base is None:
        return None
    ref = local_ref(installation.repo(base).default_branch, repo=base)
    return lambda: prepare(
        installation.checkouts[base],
        "_dev_stack_base",
        name=base,
        ref=ref,
        root=installation.worktree_root,
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

    Per unit rather than once: the commit trailer, the e2e-test session and the
    status all belong to this unit and nothing else.
    """
    # Here and not at the top: `events` imports this module.
    from agent_build_kit.pipeline.events import build_fetch_comments  # noqa: PLC0415

    repo: RepoConfig = installation.repo(unit.repo)
    profile = profiles.get(repo.profile)
    root = installation.state_dir
    # One stamp for this thread's whole run: every call in it is one run to retention.
    record_for = (unit, transcript_dir(root), datetime.now(UTC))
    declared = e2e_splits(repo, installation.config)
    # What the unit's e2e-test leaves out, and what a parked unit says it waits for.
    holds = repo_holds(installation.config, repo, root)
    e2e = E2eSession(
        unit,
        held=list(holds.held),
        lock=installation.e2e_lock,
        log=log,
        under=dev_stack_underneath(unit, installation),
        profile=profile,
        marker=repo.tests.e2e_marker,
        scope=e2e_unit_scope(repo, installation.config.global_limits),
        dev_stack=repo.dev_stack.script if repo.dev_stack else None,
        stack_versions_command=stack_versions_for(
            installation.config.verify, infra.get(repo.infra)
        ),
        env=installation.verify_env(),
        projects=repo.projects,
        output_dir=e2e_output_dir(root),
        splits=declared,
        unavailable=unavailable_markers(repo, installation.config),
        dimensions=e2e_dimensions(repo, installation.config),
    )
    planning_repo = installation.root
    # Units build in parallel, and two in one repo share its `.git`. Adding a
    # worktree, pushing, and the restack's git phases (the rebase up to its stop;
    # its continue or abort, the branch update and the rerere writes) all take
    # git's own locks there, which fail rather than wait — so those steps take
    # turns per repo. The resolver's edits do not: they, and everything else,
    # happen inside the unit's own worktree and need no turn-taking.
    unit_repo_turn = partial(file_lock, installation.locks_dir / f"repo-{unit.repo}.lock")

    def repo_turn_of(name: str) -> AbstractContextManager[object]:
        return file_lock(installation.locks_dir / f"repo-{name}.lock")

    worktree = build_worktree(installation.checkouts, root=installation.worktree_root, repo=repo)
    push = build_push(store)

    def worktree_in_turn(unit: Unit, base: str, allow_dirty: bool = False) -> Path:
        with unit_repo_turn():
            return worktree(unit, base, allow_dirty)

    def push_in_turn(branch: str, *, cwd: Path) -> str:
        with unit_repo_turn():
            return push(branch, cwd=cwd)

    forge = forges.get(repo.forge)
    tools = allowed_tools(profile, forge, repo.projects)
    account = claude_account.for_repo(installation.config, unit.repo)
    # Every change the unit builds, joined ones included: its prompts point at each.
    changes = tuple(member.change for member in unit.members())
    run = build_run(
        sandbox_repo=unit.repo,
        # The build run, and the commit step that reuses it, run under the unit's own kind.
        sandbox_tier=unit.tier,
        sandbox_changes=changes,
        account=account,
        planning_repo=planning_repo,
        allowed_tools=tools,
        log=log,
        journal=journal,
        transcript=transcript,
        record_for=record_for,
        # A unit of the repository the planning root lives in leaves the pipeline's paths be.
        planning_paths=(
            installation.planning_paths if in_repo_name(installation) == unit.repo else ()
        ),
    )
    gate_may_start, gate_resume_at = build_usage_gate(account=account)
    return UnitRunner(
        account=account,
        store=store,
        leases=Leases(lease_dir(installation.local_dir)),
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
        # The review and rework-review runs only read the diff and run nothing that needs a
        # service, so they stay at the unit-test tier whatever the unit's kind.
        run_review=build_run_review(
            sandbox_repo=unit.repo,
            sandbox_changes=changes,
            planning_repo=planning_repo,
            log=log,
            journal=journal,
            transcript=transcript,
            record_for=record_for,
            forge=forge,
            repo=repo,
            account=account,
        ),
        run_rework_review=build_run_review(
            sandbox_repo=unit.repo,
            sandbox_changes=changes,
            planning_repo=planning_repo,
            forge=forge,
            model=models().rework_review,
            log=log,
            journal=journal,
            transcript=transcript,
            record_for=record_for,
            role="rework_review",
            repo=repo,
            account=account,
        ),
        # A rejected commit goes back to the build run's agent, same policy.
        commit=build_commit(
            unit_id=unit.id,
            fix=run,
            repo=repo,
            base=local_ref(repo.default_branch, repo=unit.repo),
        ),
        commit_built=build_commit_built(unit_id=unit.id),
        run_stub_checks=build_stub_checks(profile=profile, projects=repo.projects),
        run_fixers=build_fixers(profile=profile, projects=repo.projects, repo_name=unit.repo),
        tree_state=build_tree_state(),
        branch_commits=branch_commits,
        branch_subjects=branch_subjects,
        upstream_incomplete=build_upstream_incomplete(
            store, installation.config.global_limits.bounce_limit
        ),
        base_moved=build_base_moved(store),
        base_tip=tip,
        branch_diff=branch_diff,
        restack_onto=build_restack_onto(store, repo=repo, turn=unit_repo_turn),
        move_empty_branch=build_move_empty_branch(turn=unit_repo_turn),
        run_unit_test=build_unit_test(
            profile=profile,
            root_extras=repo.tests.root_extras,
            projects=repo.projects,
            log=log,
            repo=repo,
            failures_dir=failure_bundles_dir(installation.state_dir),
            installation=installation,
            test_runs=run_ledger_path(installation.state_dir),
        ),
        on_flake=build_on_flake(store, installation, log=log),
        reproduce_test=build_reproduce(
            profile=profile,
            projects=repo.projects,
            root_extras=repo.tests.root_extras,
            workers=repo.tests.workers,
            max_workers=repo.tests.max_workers,
        ),
        run_e2e=e2e.run,
        e2e_verdict=lambda: e2e.verdict,
        e2e_result=lambda: e2e.result,
        e2e_holds=lambda: holds,
        e2e_ran_no_tests=lambda: bool(e2e.result and e2e.result.ran_no_tests),
        e2e_passed_note=e2e.passed_note,
        on_preexisting=build_on_preexisting(store, installation, log=log),
        on_product_defect=build_on_product_defect(store, installation, log=log),
        e2e_runs_whole=lambda *, cwd, base: e2e.scope(cwd=cwd, base=base).mode is E2eUnitScope.FULL,
        e2e_splits=lambda: e2e.splits(),
        on_e2e_gate=build_on_e2e_gate(store, installation, log=log),
        push=push_in_turn,
        open_pr=build_open_pr(store=store, log=log),
        linear=is_linear,
        post_status=e2e.post,
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


# What a test runner says, and the exit status it gives, for an id that collection does not find
# (pytest: "ERROR: not found: ..." and a usage error). Any other output that merely says "not
# found" is a crash, not a missing test.
NOT_FOUND = "ERROR: not found:"
NOT_FOUND_EXIT = 4


def build_reproduce(
    *,
    profile: ToolchainProfile,
    run: Run | None = None,
    projects: list[ProjectConfig] | None = None,
    root_extras: list[str] | None = None,
    workers: str | int = "auto",
    max_workers: int = 8,
) -> Callable[..., Reproduction]:
    """The runs of a fix unit's reproduction check, as `reproduce_test(cwd=, test=, runs=)`.

    A file not under the root is `SKIPPED`. The test is `GONE` only when the runner's own
    collection says it does not find the id (no tests collected, or "not found"), never from
    reading the file, since a name may be inherited or made up at collection. Alone, it is run
    by id, serially, through the profile's single-test command. Under load, the whole file it
    is in is run with the repo's parallel workers (the profile's repeat command, which keeps
    them), so the file's other tests are running beside it, and the run counts as a failure
    only when the output names the test. A run alone counts as a failure when it exits as a
    failure for any reason: the test failing, erroring or timing out. A profile without the
    single-test or the repeat command cannot make the check, which is `SKIPPED`."""
    run = run or _run_limited

    def reproduce_test(*, cwd: Path, test: str, runs: int) -> Reproduction:
        file = test.partition("::")[0]
        where, toolchain = cwd, profile
        for project in projects or []:
            if (cwd / project.path / file).is_file():
                where, toolchain = cwd / project.path, profiles.get(project.profile)
                break
        if not (where / file).is_file():
            # The id is not under this root (or its file is unreadable): the check cannot be
            # made, and a guess is not a reason to satisfy the unit.
            return Reproduction(outcome=Outcome.SKIPPED, note=f"{file} is not under {where}")
        rerun = getattr(toolchain, "serial_rerun_command", None)
        if rerun is None or not isinstance(toolchain, RepeatsTests):
            return Reproduction(outcome=Outcome.SKIPPED, note="the profile cannot run one test")
        base = toolchain.test_commands_all(
            where, root_extras=root_extras or [], workers=workers, max_workers=max_workers
        )
        found = next(
            (
                (command, again)
                for command in base
                if (again := toolchain.repeat_command(command, [test])) is not None
            ),
            None,
        )
        if found is None:
            return Reproduction(outcome=Outcome.SKIPPED, note="no test command runs the test")
        command, _ = found
        alone = rerun(command, [test])
        loaded = toolchain.repeat_command(command, [file]) or alone

        def attempt(argv: list[str], *, whole_file: bool) -> Attempt:
            result = run(argv, cwd=where)
            output = f"{result.stdout}\n{result.stderr}"
            if test in failed_ids(toolchain, output):
                return Attempt.FAILED
            if result.returncode != 0 and (
                result.returncode == toolchain.no_tests_collected_exit
                or (result.returncode == NOT_FOUND_EXIT and NOT_FOUND in output)
            ):
                return Attempt.NOT_COLLECTED
            if not whole_file and not toolchain.tolerates_exit(argv, result.returncode):
                return Attempt.FAILED
            return Attempt.PASSED

        return check_reproduction(
            test,
            runs,
            alone=lambda: attempt(alone, whole_file=False),
            loaded=lambda: attempt(loaded, whole_file=True),
        )

    return reproduce_test
