"""The scheduled tracks: health, improve, recommend, and the implement pass.

Each track runs **once per repo** in the workspace (`abk.yaml`'s `repos`, in
order) — its own agent run(s) through the runtime, its own budget, its own run-log
entry in the planning repo's state directory, and its own worktree and PRs in
that repo. A repo is eligible only when its checkout is a git repo whose
`origin` is the GitHub repo abk.yaml names and `gh` can see it; anything else
is logged and skipped (see `eligible_projects`), so a repo can be listed
before it exists on GitHub without failing the run.

- `health`: daily, read-only, no worktree — "is something actually wrong right
  now". Fans out the health playbooks, cross-checks findings against the
  tracked-issues list so a problem with a PR already open is not re-proposed,
  and writes a Status line. ATTENTION or URGENT — a genuinely new finding —
  runs `implement` for the same repo straight away instead of waiting for the
  weekly improve run; OK or PENDING RESOLUTION costs nothing more.
- `improve`: weekly — the improve playbooks (read-only) find "this could be
  better" findings, then `implement` (its own worktree) opens up to
  `tracks.implement_max_prs` PRs. Two invocations rather than one so a heavy
  discovery pass cannot spend the budget the implementing phase needs. A
  nonzero exit is never fatal to the next phase or repo: implement falls back
  to whatever candidates the run log already holds.
- `recommend`: weekly on a different day — bigger-picture playbooks (test
  coverage, technical debt, architecture, cost/performance) that mostly
  produce recommendations for a human, plus the same implement pass for the
  rare bounded finding.
- `implement` on its own works down the existing backlog on demand; `--focus`
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
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit import forges, runtimes
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_guard import current_usage, may_start_unit
from agent_build_kit.runtimes import AgentInterrupted, AgentRateLimited, AgentRequest
from agent_build_kit.runtimes.base import AgentRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, build_argv

RUN_ID = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
TRACKS = ("health", "improve", "recommend")
PHASES = (*TRACKS, "implement")

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
        "__IMPLEMENT_MAX_PRS__",
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
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


# --- which repos ---------------------------------------------------------------


def repo_reachable(name: str, inst: Installation) -> bool:
    """Whether the repo's host will answer for it — a track pulls and opens
    pull requests there.

    Asked of the forge, which is the only thing that knows how: this used to
    shell `gh repo view` directly, one of the two sites bypassing the `gh`
    chokepoint, and it read every Azure DevOps repo as unreachable.
    """
    forge, repo = inst.forge_of(name)
    problem = forge.check_access(repo)
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


def default_branch_of(repo_dir: Path) -> str:
    """The branch `origin/HEAD` points at, or `main` when the checkout does
    not record one."""
    result = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo_dir)
    if result.returncode != 0:
        return "main"
    return result.stdout.strip().removeprefix("origin/") or "main"


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
    """Turns --focus into the sentence implement.md's __FOCUS_HINT__ is
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
        # candidates) and its own -implement.md (just that run's output,
        # never a candidate source) — prefer the former when both exist.
        non_implement = [m for m in matches if not m.name.endswith("-implement.md")]
        matches = non_implement or matches
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
        "__IMPLEMENT_MAX_PRS__": str(inst.config.tracks.implement_max_prs),
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
    inst: Installation, project: Project, *, prompt: str, worktree: str | None
) -> AgentRequest:
    """One phase's run, with its model and tool lists from `tracks`: in the
    project's checkout, the planning repo readable for its run log, and the
    whole machine-readable record kept as the raw output."""
    tracks = inst.config.tracks
    return AgentRequest(
        prompt=prompt,
        cwd=project.path,
        add_dirs=(inst.root,),
        model=tracks.model,
        allowed_tools=tracks.allowed_tools,
        denied_tools=denied_tools_value(tracks.disallowed_tools),
        permission_mode="edit",
        worktree=worktree,
        keep_record=True,
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


def claude_phase(
    inst: Installation,
    *,
    project: Project,
    name: str,
    worktree: str | None,
    focus: str | None = None,
    dry_run: bool = False,
    runtime: AgentRuntime | None = None,
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
        inst, project, prompt=render_prompt(inst, project, name, focus), worktree=worktree
    )
    if dry_run:
        _print_dry_run(project, name, request, agent)
        return 0

    output_dir = raw_output_dir(inst)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{RUN_ID}-{project.name}-{name}.json"

    log(f"[{project.name}] phase: {name} (session window only)")
    try:
        result = agent.run(request)
    except (AgentRateLimited, AgentInterrupted) as error:
        log(f"[{project.name}] {name} phase stopped — {error}. Continuing regardless.")
        return 1
    output_file.write_text(result.raw)

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
    decision = may_start_unit(current_usage())
    log(decision.reason if decision.may_start else f"not starting — {decision.reason}")
    return decision.may_start


def implement(
    inst: Installation,
    project: Project,
    focus: str | None = None,
    *,
    dry_run: bool = False,
    runtime: AgentRuntime | None = None,
) -> int:
    return claude_phase(
        inst,
        project=project,
        name="implement",
        worktree=f"abk-{RUN_ID}",
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
        worktree=None,
        dry_run=dry_run,
        runtime=runtime,
    )
    if dry_run:
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
        f"something already pending — running implement now rather than "
        f"waiting for the weekly improve run."
    )
    implement_rc = implement(inst, project, runtime=runtime)
    return 1 if (health_rc != 0 or implement_rc != 0) else 0


def discover_then_implement(track: str):
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
            worktree=None,
            dry_run=dry_run,
            runtime=runtime,
        )
        # Always runs, even if discovery exited nonzero — implement falls
        # back to whatever candidates already exist in the run log.
        implement_rc = implement(inst, project, dry_run=dry_run, runtime=runtime)
        return 1 if (discover_rc != 0 or implement_rc != 0) else 0

    return run


DISPATCH = {
    "health": health,
    "improve": discover_then_implement("improve"),
    "recommend": discover_then_implement("recommend"),
    "implement": implement,
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
        if DISPATCH[phase](inst, project, focus, dry_run=dry_run, runtime=runtime) != 0:
            failed.append(project.name)
    log(
        f"{phase} run complete for {[p.name for p in projects]} — check "
        f"{inst.state_dir}/{RUN_ID}-<project>-*.md were written and pushed."
        + (f" Nonzero exit for: {failed}" if failed else "")
    )
    return 1 if failed else 0
