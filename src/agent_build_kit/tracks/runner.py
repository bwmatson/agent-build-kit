"""The scheduled tracks: health, improve and recommend, and the propose pass.

Each track runs **once per repo** in the workspace (`abk.yaml`'s `repos`, in
order) — its own agent run(s) through the runtime, its own budget, and its own
run-log entry in the planning repo's state directory. A repo is eligible only
when its checkout is a git repo whose `origin` is the repo abk.yaml names, on a
host that answers for it; anything else is logged and skipped (see
`eligible_projects`), so a repo can be listed before it exists on its host
without failing the run.

**A track never edits a repo or opens a pull request.** `propose` writes what it
found as an OpenSpec change in the planning repo; the runner commits it to the
default branch if it validates, and the pipeline's tick then plans and builds
it, with a review loop and the test tiers around every unit. Work written by a
track directly would go around all of that, and the tick would later find it
already done.

- `health`: daily, read-only — "is something actually wrong right
  now". Fans out the health playbooks, cross-checks findings against the
  tracked-issues list so a problem already in flight is not re-proposed, and
  writes a Status line. ATTENTION or URGENT — a genuinely new finding — runs
  `propose` for the same repo straight away instead of waiting for the weekly
  improve run; OK or PENDING RESOLUTION costs nothing more.
- `improve`: weekly — the improve playbooks (read-only) find "this could be
  better" findings, then `propose` writes up to `tracks.propose_max_issues` of
  them as one change. Two invocations rather than one so a heavy discovery pass
  cannot spend the budget the proposing phase needs. A nonzero exit is never
  fatal to the next phase or repo: propose falls back to whatever candidates
  the run log already holds.
- `recommend`: weekly on a different day — bigger-picture playbooks (test
  coverage, technical debt, architecture, cost/performance) that mostly
  produce recommendations for a human, plus the same propose pass for the rare
  bounded finding.
- `propose` on its own works down the existing backlog on demand; `--focus`
  biases which run-log entries it reads first (a track name, or a run id).

Every phase's run log has a filename built from this process's RUN_ID and
the repo name (`<state_dir>/<RUN_ID>-<repo>-<track>.md`), injected into the
prompt as a placeholder rather than left for the agent to invent — health's
status readback depends on it being predictable.

The prompts are Markdown files with `__PLACEHOLDER__` tokens (`PLACEHOLDERS`
below); `tracks.prompts_dir` overrides the built-in set file by file.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit import forges, runtimes
from agent_build_kit.forges.transport import TransportError
from agent_build_kit.init.propose import validation_errors
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import shell
from agent_build_kit.pipeline.planning_repo import default_branch_of, is_repo
from agent_build_kit.pipeline.planning_repo import restore_default_branch as _restore
from agent_build_kit.pipeline.usage_guard import (
    current_usage,
    decide_start,
    may_start_unit,
    reading_as,
)
from agent_build_kit.runtimes import AgentInterrupted, AgentRateLimited, AgentRequest
from agent_build_kit.runtimes.base import AgentRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, build_argv

RUN_ID = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
TRACKS = ("health", "improve", "recommend")
PHASES = (*TRACKS, "propose")

# What a phase returns when the planning repo's default branch was rewritten:
# not a failed phase the next one can follow, but a reason to stop the run.
STOPPED = 2

# Every token a prompt file may use. The prompt test holds the shipped files
# to this set, and `placeholders()` fills every one of them for every phase.
PLACEHOLDERS = frozenset(
    {
        "__RUN_ID__",
        "__RUN_LOG__",
        "__PROJECT__",
        "__PROJECT_DIR__",
        "__PROJECT_REPO__",
        "__PROJECT_REPO_URL__",
        "__PROJECT_DESCRIPTION__",
        "__PROJECT_CONSUMES__",
        "__WORKSPACE_REPOS__",
        "__PLANNING_DIR__",
        "__STATE_DIR__",
        "__PROMPTS_DIR__",
        "__MAX_ISSUES__",
        "__PROPOSED_CHANGE__",
        "__FOCUS_HINT__",
    }
)
_PLACEHOLDER = re.compile(r"__[A-Z_]+__")

# github.com remotes in either ssh (git@github.com:<owner>/<name>.git) or
# https (https://github.com/<owner>/<name>(.git)) form.

# How many lines of each rendered prompt a dry run shows.
DRY_RUN_PROMPT_LINES = 40


class Project(Frozen):
    """One eligible repo: its abk.yaml entry plus the resolved checkout."""

    name: str  # the abk.yaml key
    path: Path
    repo: str  # GitHub owner/name
    default_branch: str = "main"
    description: str = ""
    consumes: list[str] = []

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.repo}"


# `gh repo view` stays in the base rather than in the GitHub forge's reads: it is
# not a PR read, and the forge's list is also what a unit's agents are given.
TRACK_TOOLS = (
    "Read Grep Glob Edit Write TodoWrite Agent Skill WebSearch WebFetch "
    "Bash(git *) Bash(uv run *) Bash(pre-commit *) Bash(gh repo view*) "
    "Bash(docker compose config*) Bash(abk check*) Bash(abk tags*)"
)


def allowed_tools_value(configured: str | None) -> str:
    """The workspace's allow list, or the built-in one with every forge's PR reads."""
    if configured is not None:
        return configured
    reads = " ".join(f"Bash({prefix}*)" for prefix in forges.read_prefixes())
    return f"{TRACK_TOOLS} {reads}"


def denied_tools_value(configured: str) -> str:
    """The workspace's deny list, plus every forge's way of merging.

    Added rather than defaulted, so a workspace that overrides
    `tracks.disallowed_tools` cannot drop them by accident.
    """
    merges = " ".join(f"Bash({prefix}*)" for prefix in forges.denied_prefixes())
    return f"{merges} {configured}".strip()


def log(message: str) -> None:
    print(f"[{RUN_ID}] {message}", flush=True)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return shell.git(cwd, *args, check=False)


# --- which repos ---------------------------------------------------------------


def repo_reachable(name: str, inst: Installation) -> bool:
    """Whether the repo's host will answer for it — a track pulls and opens
    pull requests there.

    Asked of the forge, which is the only thing that knows how: this used to
    shell `gh repo view` directly, one of the two sites bypassing the `gh`
    chokepoint, and it read every Azure DevOps repo as unreachable.
    """
    forge, repo = inst.forge_of(name)
    try:
        problem = forge.check_access(repo)
    except TransportError as error:
        problem = f"cannot reach {forges.key(repo)}: {error}"
    if problem:
        log(f"{forges.key(repo)}: {problem}")
    return not problem


def eligible_projects(inst: Installation, only: str | None = None) -> list[Project]:
    """abk.yaml's repos filtered down to the ones a track can work on: a git
    checkout whose `origin` is the repo the config names, on a host that
    answers for it. Anything else is logged and skipped — not an error, so a
    repo can be listed before it has a remote."""
    projects: list[Project] = []
    for name, repo in inst.config.repos.items():
        if only and name != only:
            continue
        path = repo.path.expanduser().resolve()
        if not (path / ".git").exists():
            log(f"skip {name}: {path} is not a git checkout")
            continue
        remote = _git(["remote", "get-url", "origin"], path)
        if remote.returncode != 0:
            log(f"skip {name}: no `origin` remote (nothing to pull from or open PRs against)")
            continue
        origin = forges.identify(remote.stdout.strip())
        if origin is None:
            log(f"skip {name}: no forge recognises origin {remote.stdout.strip()!r}")
            continue
        declared = forges.get(repo.forge).identity(repo)
        if forges.key(origin).lower() != forges.key(declared).lower():
            log(
                f"skip {name}: origin is {forges.key(origin)} "
                f"but abk.yaml says {forges.key(declared)}"
            )
            continue
        if not repo_reachable(name, inst):
            log(f"skip {name}: {forges.key(declared)} is not reachable")
            continue
        projects.append(
            Project(
                name=name,
                path=path,
                repo=forges.key(declared),
                default_branch=repo.default_branch,
                description=repo.description,
                consumes=list(repo.consumes),
            )
        )
    if only and not projects:
        log(f"--project {only}: not a repo in abk.yaml, or not eligible (see above)")
    return projects


# --- pulling ---------------------------------------------------------------------


def pull(repo_dir: Path, branch: str) -> bool:
    for cmd in (["checkout", branch], ["pull", "--ff-only", "origin", branch]):
        result = _git(cmd, repo_dir)
        if result.returncode != 0:
            log(f"git {' '.join(cmd)} in {repo_dir} failed:\n{result.stderr}")
            return False
    return True


def pull_planning(inst: Installation) -> bool:
    """The planning repo is where every phase writes and pushes its run log:
    if it cannot be brought to its latest default branch, nothing downstream
    is safe. `planning.self_pull: false` leaves it as it is."""
    if not inst.config.planning.self_pull:
        log(f"planning.self_pull is off — not pulling {inst.root}")
        return True
    log(f"pulling the planning repo ({inst.root})")
    if not pull(inst.root, default_branch_of(inst.root)):
        log("FATAL: cannot update the planning repo")
        return False
    return True


# --- paths -----------------------------------------------------------------------


def prompts_dir(inst: Installation) -> Path:
    """`tracks.prompts_dir` when set (relative to the planning root), else
    the prompts shipped with the package."""
    configured = inst.config.tracks.prompts_dir
    if configured is not None:
        configured = configured.expanduser()
        return configured if configured.is_absolute() else inst.root / configured
    # Package data: the one place the module's own location is the right answer.
    return Path(__file__).resolve().parent / "prompts"


def raw_output_dir(inst: Installation) -> Path:
    return inst.root / inst.config.tracks.raw_output_dir


def run_log(inst: Installation, project: Project, track: str) -> Path:
    return inst.state_dir / f"{RUN_ID}-{project.name}-{track}.md"


# --- prompts ---------------------------------------------------------------------


def resolve_focus(inst: Installation, project: Project, focus: str | None) -> str:
    """Turns --focus into the sentence propose.md's __FOCUS_HINT__ is
    replaced with, for one project. `focus` is either a track name
    (resolving to that project's most recent run log for the track) or a
    run-id prefix (resolving to the project's run-log filename it matches,
    most recent if more than one)."""
    default = (
        "none — use your normal judgment across all recent run-log entries "
        "for this project, weighted toward whatever's most recent"
    )
    if not focus:
        return default

    state_dir = inst.state_dir
    if focus in TRACKS:
        matches = sorted(state_dir.glob(f"*-{project.name}-{focus}.md"))
        if not matches:
            return (
                f"none — no {focus} run log entries exist yet for {project.name}, "
                f"fall back to normal judgment"
            )
    else:
        matches = sorted(state_dir.glob(f"{focus}-{project.name}-*.md"))
        # An exact run-id can match both its source track's log (real
        # candidates) and the propose phase's own (just that run's output,
        # never a candidate source) — prefer the former when both exist.
        # `-implement.md` is what the phase was called before it stopped
        # editing code, and installations that ran it still have those logs.
        own = ("-propose.md", "-propose-rejected.md", "-implement.md")
        candidates = [m for m in matches if not m.name.endswith(own)]
        matches = candidates or matches
        if not matches:
            return (
                f"none — no run log filename for {project.name} matched '{focus}', "
                f"fall back to normal judgment"
            )
    return (
        f"{matches[-1]} — look at this run's Actionable candidates first, "
        f"before the general backlog. Still apply every other rule as normal "
        f"(tracked-issues.md dedup, skip already-actioned, pick "
        f"low-risk/well-evidenced ones) — this only changes which entry you "
        f"start with, not what qualifies."
    )


def workspace_repos(inst: Installation) -> str:
    """A bullet list of every repo in the workspace, for the prompts' scope
    sections."""
    lines = []
    for name, repo in inst.config.repos.items():
        description = repo.description.strip() or "(no description in abk.yaml)"
        lines.append(f"- {name} — {description}")
    return "\n".join(lines) or "- (no repos configured)"


def placeholders(
    inst: Installation, project: Project, phase: str, focus: str | None = None
) -> dict[str, str]:
    """Every value the prompt files may reference, so what they instruct the
    agent with cannot drift from what is configured or which project this
    invocation is for."""
    values = {
        "__RUN_ID__": RUN_ID,
        "__RUN_LOG__": str(run_log(inst, project, phase)),
        "__PROJECT__": project.name,
        "__PROJECT_DIR__": str(project.path),
        "__PROJECT_REPO__": project.repo,
        "__PROJECT_REPO_URL__": project.repo_url,
        "__PROJECT_DESCRIPTION__": project.description.strip() or "(no description in abk.yaml)",
        "__PROJECT_CONSUMES__": ", ".join(project.consumes) or "nothing",
        "__WORKSPACE_REPOS__": workspace_repos(inst),
        "__PLANNING_DIR__": str(inst.root),
        "__STATE_DIR__": str(inst.state_dir),
        "__PROMPTS_DIR__": str(prompts_dir(inst)),
        "__MAX_ISSUES__": str(inst.config.tracks.propose_max_issues),
        "__PROPOSED_CHANGE__": proposed_change(project),
        "__FOCUS_HINT__": resolve_focus(inst, project, focus),
    }
    assert set(values) == PLACEHOLDERS
    return values


def render_prompt(
    inst: Installation, project: Project, phase: str, focus: str | None = None
) -> str:
    text = (prompts_dir(inst) / f"{phase}.md").read_text()
    for placeholder, value in placeholders(inst, project, phase, focus).items():
        text = text.replace(placeholder, value)
    unknown = sorted(set(_PLACEHOLDER.findall(text)))
    if unknown:
        raise ValueError(f"{phase}.md uses unknown placeholders: {', '.join(unknown)}")
    return text


# --- running a phase -------------------------------------------------------------


def phase_request(
    inst: Installation,
    project: Project,
    *,
    prompt: str,
    at: Path | None = None,
    change_dir: Path | None = None,
) -> AgentRequest:
    """One phase's run, with its model and tool lists from `tracks`.

    A discovery phase runs in the project's checkout with the planning repo
    readable for its run log. `at` turns that around for the propose phase,
    which runs in the planning repo — what it writes is a change — with the
    project readable beside it. Whichever is not the working directory is the
    one added, so neither phase can write where it is only meant to read by
    habit rather than by grant.
    """
    tracks = inst.config.tracks
    cwd = at or project.path
    return AgentRequest(
        prompt=prompt,
        cwd=cwd,
        add_dirs=tuple(path for path in (inst.root, project.path) if path != cwd),
        model=tracks.model,
        allowed_tools=allowed_tools_value(tracks.allowed_tools),
        denied_tools=denied_tools_value(tracks.disallowed_tools),
        permission_mode="edit",
        planning_repo=inst.root,
        planning_state_dir=inst.state_dir,
        planning_change_dir=change_dir,
        # No track runs in a worktree: discovery reads the checkout, and
        # propose writes a change in the planning repo. The implement flow was
        # the only phase that needed a branch of its own, and it is gone.
        keep_record=True,
    )


# --- the planning repo --------------------------------------------------------------


class PlanningHead(Frozen):
    """The planning repo's default branch and where it pointed before a phase."""

    branch: str
    head: str


def _keep_raw_output_untracked(inst: Installation) -> None:
    """Excludes the raw output directory in this clone, so a planning repo whose
    `.gitignore` does not name it still reads clean after a phase."""
    exclude = _git(["rev-parse", "--git-path", "info/exclude"], inst.root).stdout.strip()
    if not exclude:
        return
    path = inst.root / exclude
    entry = f"/{inst.config.tracks.raw_output_dir.strip('/')}/"
    existing = path.read_text() if path.exists() else ""
    if entry not in existing.splitlines():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            existing + ("" if existing.endswith("\n") or not existing else "\n") + entry + "\n"
        )


def record_planning(inst: Installation) -> PlanningHead | None:
    """The default branch and its head, taken before a phase; None when the
    planning root is not a git repo (nothing to keep or commit)."""
    if not is_repo(inst.root):
        return None
    _keep_raw_output_untracked(inst)
    branch = default_branch_of(inst.root)
    head = _git(["rev-parse", "--verify", "-q", branch], inst.root)
    return PlanningHead(branch=branch, head=head.stdout.strip()) if head.returncode == 0 else None


def restore_default_branch(inst: Installation, branch: str) -> bool:
    """Puts the planning repo back on `branch`, keeping any stray branch the
    phase left it on. False when it cannot be put back."""
    return _restore(inst.root, branch, log)


def settle_planning(inst: Installation, before: PlanningHead, project: Project, name: str) -> bool:
    """After a phase: the planning repo back on its default branch, which must
    not have been rewritten, then the phase's files committed and pushed.
    False stops the run."""
    if not restore_default_branch(inst, before.branch):
        return False
    ancestor = _git(["merge-base", "--is-ancestor", before.head, before.branch], inst.root)
    if ancestor.returncode != 0:
        log(
            f"FATAL: {before.branch} in the planning repo was rewritten during the {name} "
            f"phase (it was {before.head[:10]}) — committing nothing; stopping the run"
        )
        return False
    changes = _vet_proposed_change(inst, project) if name == "propose" else []
    commit_bookkeeping(inst, before.branch, project, name, changes)
    return True


def _vet_proposed_change(inst: Installation, project: Project) -> list[str]:
    """The propose phase's change, if it may be committed: its path relative to
    the planning repo, in a list so "nothing to commit" is an empty one.

    A change is committed straight to the default branch, where the tick plans
    it, so this is the only check between a timer-written spec and the pipeline.
    One that does not validate is worse than none: the tick reads it, cannot
    plan it, and says so a cycle later with nobody present. So it is moved out
    of `changes/` — the tick plans whatever is there, committed or not — into
    the state directory where a human can still read it, and a note saying why
    is committed in its place, so the tracker's claim that a change is in
    flight does not stand with nothing anywhere to contradict it.

    A run that wrote no change is fine: nothing surviving is a valid outcome.
    """
    change = proposed_change(project)
    directory = inst.changes_dir / change
    if not directory.exists():
        return []
    errors = validation_errors(
        inst.root,
        change,
        repos=tuple(inst.repos),
        specs_dir=inst.config.planning.specs_dir,
    )
    if not errors:
        try:
            return [directory.relative_to(inst.root).as_posix()]
        except ValueError:
            log(f"[{project.name}] {change} is outside the planning repo; not committing it")
            return []

    kept = inst.state_dir / "rejected-changes" / change
    kept.parent.mkdir(parents=True, exist_ok=True)
    if kept.exists():
        shutil.rmtree(kept)
    shutil.move(str(directory), str(kept))
    note = run_log(inst, project, "propose-rejected")
    note.write_text(
        f"# Rejected change: {change}\n\n"
        f"The propose phase for `{project.name}` wrote this change, and it did not "
        f"validate, so it was not committed and not offered to the pipeline. Its files "
        f"are kept in `{kept.relative_to(inst.root).as_posix()}`.\n\n"
        + "\n".join(f"- {error}" for error in errors)
        + "\n"
    )
    log(f"[{project.name}] {change} did not validate — set aside, not committed:")
    for error in errors:
        log(f"[{project.name}]   {error}")
    return []


def commit_bookkeeping(
    inst: Installation,
    branch: str,
    project: Project,
    name: str,
    changes: Sequence[str] = (),
) -> None:
    """Commits and pushes the phase's Markdown under the state directory: run
    logs and `tracked-issues.md`, plus any change the phase wrote (already
    vetted). The rest of that directory is the tick's live state, which the
    operator commits and a tick may be rewriting right now.
    A rejected push is retried once after a fast-forward; a second rejection
    is reported and the commit stays."""
    notes = f":(glob){inst.state_dir.relative_to(inst.root).as_posix()}/**/*.md"
    paths = [notes, *changes]
    _git(["add", "-A", "--", *paths], inst.root)
    if _git(["diff", "--cached", "--quiet", "--", *paths], inst.root).returncode == 0:
        return
    message = f"track: {RUN_ID} {project.name} {name}"
    committed = _git(["commit", "-q", "-m", message, "--", *paths], inst.root)
    if committed.returncode != 0:
        log(f"[{project.name}] committing the {name} bookkeeping failed:\n{committed.stderr}")
        return
    if _git(["remote", "get-url", "origin"], inst.root).returncode != 0:
        return
    push = _git(["push", "origin", branch], inst.root)
    if push.returncode != 0:
        # --autostash: the graph page and units.json are routinely dirty, and
        # a rebase refuses to start over unstaged changes.
        pulled = _git(["pull", "--rebase", "--autostash", "origin", branch], inst.root)
        if pulled.returncode != 0:
            log(f"[{project.name}] pulling before the retry failed:\n{pulled.stderr}")
        push = _git(["push", "origin", branch], inst.root)
    if push.returncode != 0:
        log(
            f"[{project.name}] push of the {name} bookkeeping was rejected twice — the commit "
            f"is kept in {inst.root}:\n{push.stderr}"
        )


def _print_dry_run(
    project: Project, name: str, request: AgentRequest, runtime: AgentRuntime
) -> None:
    lines = request.prompt.splitlines()
    print(
        f"--- [{project.name}] {name}: prompt (first {DRY_RUN_PROMPT_LINES} of {len(lines)} lines)"
    )
    print("\n".join(lines[:DRY_RUN_PROMPT_LINES]))
    if isinstance(runtime, ClaudeCodeRuntime):
        print(f"--- [{project.name}] {name}: command (prompt elided)")
        print(shlex.join(build_argv(request.model_copy(update={"prompt": "<prompt>"}))))
    else:
        print(f"--- [{project.name}] {name}: {runtime.name} request (prompt elided)")
        print(request.model_dump(exclude={"prompt", "on_event"}))


def proposed_change(project: Project) -> str:
    """The change a propose run writes, named for its project and this run.

    Fixed before the run rather than chosen by the model, because the run is
    only useful if what it wrote can be validated, and validating a change
    means knowing which one to validate.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", project.name.lower()).strip("-") or "workspace"
    return f"{slug}-track-{RUN_ID}"


def claude_phase(
    inst: Installation,
    *,
    project: Project,
    name: str,
    focus: str | None = None,
    dry_run: bool = False,
    runtime: AgentRuntime | None = None,
    at: Path | None = None,
    change_dir: Path | None = None,
) -> int:
    """Runs one phase for one project through the agent runtime (cwd = that
    project's checkout, the planning repo added as an extra dir for run
    logs), writes its raw record under the planning root, and returns 0 or 1.
    Never raises on a failed run — an otherwise failed phase should not stop
    whatever phase or project runs after it. A refused run — the window
    spent, or the process killed — keeps no raw output file: it is not a
    run, and what the CLI said of it is logged whole. No dollar budget: the session
    window is the limit, and `has_headroom` (below) is what keeps a timer
    from spending into credits — a guessed dollar ceiling beside that drifts
    from real cost, and set too low it refuses to start a run rather than
    bounding one. A dry run prints the rendered prompt and the command
    instead of running it."""
    agent = runtime or runtimes.active()
    request = phase_request(
        inst,
        project,
        prompt=render_prompt(inst, project, name, focus),
        at=at,
        change_dir=change_dir,
    )
    if dry_run:
        _print_dry_run(project, name, request, agent)
        return 0

    output_dir = raw_output_dir(inst)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{RUN_ID}-{project.name}-{name}.json"

    log(f"[{project.name}] phase: {name} (session window only)")
    before = record_planning(inst)
    try:
        result = agent.run(request)
    except (AgentRateLimited, AgentInterrupted) as error:
        log(f"[{project.name}] {name} phase stopped — {error}. Continuing regardless.")
        if before is not None and not settle_planning(inst, before, project, name):
            return STOPPED
        return 1
    output_file.write_text(result.raw)
    if before is not None and not settle_planning(inst, before, project, name):
        return STOPPED

    if not result.ok:
        log(
            f"[{project.name}] {name} phase failed — {result.error} — see "
            f"{output_file}. Continuing regardless."
        )
        return 1
    log(f"[{project.name}] {name} phase done — raw output: {output_file}")
    return 0


def read_status(path: Path) -> str | None:
    """Pulls the `**Status:** OK|PENDING RESOLUTION|ATTENTION|URGENT` line
    health.md is instructed to write. Returns None if the file is missing
    (the phase failed before writing it) or the line is not there in the
    expected shape — callers treat that as "can't tell", not as OK."""
    if not path.exists():
        return None
    match = re.search(
        r"\*\*Status:\*\*\s*(OK|PENDING RESOLUTION|ATTENTION|URGENT)",
        path.read_text(),
    )
    return match.group(1) if match else None


# --- the tracks ----------------------------------------------------------------


def has_headroom() -> bool:
    """Whether the session window has room to start a track.

    The tracks run on timers, which fire whether or not there is headroom,
    and an account with credits enabled spends real money past the window
    rather than queueing. The next timer is the retry; a daily or weekly
    track does not need a scheduled resume the way a five-minute tick does.
    """
    with reading_as("tracks"):
        decision = decide_start(read=current_usage, decide=may_start_unit)
    log(decision.reason if decision.may_start else f"not starting — {decision.reason}")
    return decision.may_start


def propose(
    inst: Installation,
    project: Project,
    focus: str | None = None,
    *,
    dry_run: bool = False,
    runtime: AgentRuntime | None = None,
) -> int:
    """Turn this project's findings into one change for the pipeline to build.

    Runs in the planning repo, not in a worktree of the project: what it writes
    is a change, and the project's checkout is there to be read. The pipeline
    turns the change's task groups into branches and pull requests itself, with
    a build and review loop around each — which is the whole reason a track
    does not open one directly.
    """
    return claude_phase(
        inst,
        project=project,
        name="propose",
        at=inst.root,
        change_dir=inst.changes_dir / proposed_change(project),
        focus=focus,
        dry_run=dry_run,
        runtime=runtime,
    )


def health(
    inst: Installation,
    project: Project,
    focus: str | None = None,
    *,
    dry_run: bool = False,
    runtime: AgentRuntime | None = None,
) -> int:
    health_rc = claude_phase(
        inst,
        project=project,
        name="health",
        dry_run=dry_run,
        runtime=runtime,
    )
    if dry_run or health_rc == STOPPED:
        return health_rc
    path = run_log(inst, project, "health")
    status = read_status(path)
    if status is None:
        log(
            f"[{project.name}] couldn't determine health status ({path} missing "
            f"or unparseable) — not triggering implement early; the next "
            f"scheduled improve run will still pick up any candidates."
        )
        return health_rc

    log(f"[{project.name}] health status: {status}")
    if status in ("OK", "PENDING RESOLUTION"):
        # OK: nothing wrong. PENDING RESOLUTION: something is wrong but a PR
        # is already open for it (tracked-issues.md) — nothing new to do.
        return health_rc

    log(
        f"[{project.name}] status is {status} — a genuinely new finding, not "
        f"something already pending — proposing a change now rather than "
        f"waiting for the weekly improve run."
    )
    propose_rc = propose(inst, project, runtime=runtime)
    return 1 if (health_rc != 0 or propose_rc != 0) else 0


def discover_then_propose(track: str):
    def run(
        inst: Installation,
        project: Project,
        focus: str | None = None,
        *,
        dry_run: bool = False,
        runtime: AgentRuntime | None = None,
    ) -> int:
        discover_rc = claude_phase(
            inst,
            project=project,
            name=track,
            dry_run=dry_run,
            runtime=runtime,
        )
        if discover_rc == STOPPED:
            return STOPPED
        # Always runs, even if discovery exited nonzero — propose falls
        # back to whatever candidates already exist in the run log.
        propose_rc = propose(inst, project, dry_run=dry_run, runtime=runtime)
        return 1 if (discover_rc != 0 or propose_rc != 0) else 0

    return run


DISPATCH = {
    "health": health,
    "improve": discover_then_propose("improve"),
    "recommend": discover_then_propose("recommend"),
    "propose": propose,
}


def run_track(
    inst: Installation,
    phase: str,
    *,
    only: str | None = None,
    focus: str | None = None,
    dry_run: bool = False,
    runtime: AgentRuntime | None = None,
) -> int:
    """One track across every eligible repo: headroom check, pull the
    planning repo, then per repo pull and dispatch. Returns 1 if any repo
    failed. A dry run skips the checks and the pulls and prints what each
    phase would run. `runtime` is what every phase runs on; the active one
    when not given."""
    if not dry_run:
        if not has_headroom():
            return 0
        if not pull_planning(inst):
            return 1
    projects = eligible_projects(inst, only)
    if not projects:
        log("no eligible projects — nothing to do.")
        return 0

    failed: list[str] = []
    for project in projects:
        log(f"=== {phase} for {project.name} ({project.path}, {project.repo})")
        if not dry_run and not pull(project.path, project.default_branch):
            log(f"[{project.name}] couldn't update to latest {project.default_branch} — skipping")
            failed.append(project.name)
            continue
        rc = DISPATCH[phase](inst, project, focus, dry_run=dry_run, runtime=runtime)
        if rc != 0:
            failed.append(project.name)
        if rc == STOPPED:
            log("the planning repo's default branch was rewritten — stopping the run")
            break
    log(
        f"{phase} run complete for {[p.name for p in projects]} — check "
        f"{inst.state_dir}/{RUN_ID}-<project>-*.md were written and pushed."
        + (f" Nonzero exit for: {failed}" if failed else "")
    )
    return 1 if failed else 0
