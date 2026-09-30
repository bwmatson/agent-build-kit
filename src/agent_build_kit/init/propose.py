"""The propose step of `abk init`: a first change per repo, written by a model.

A repo joins the workspace with two changes queued — its testing
infrastructure, so an agent can change it safely, and its code standards,
from the researched recommendations — or only the second when the repo has
no code yet. Each is an OpenSpec change the pipeline will build like any
other, so it has to pass the same two checks a hand-written one does:
`openspec validate --strict` and the task-group tag contract (`work_graph`).
The model gets one repair round with the errors; a second failure raises,
with the files left in place for a person to finish.

The agent runs in the planning repo with the code repo added read-only
(`--add-dir`), and may write only under `openspec/changes/<change>/`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from agent_build_kit import openspec
from agent_build_kit.config import active
from agent_build_kit.init.claude_call import RunClaude, runtime_for, succeeded
from agent_build_kit.init.detect import RepoDetection
from agent_build_kit.init.scaffold import render_rules
from agent_build_kit.pipeline.work_graph import validate_tasks
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.base import AgentRuntime

Kind = Literal["testing-infrastructure", "code-standards"]

ALLOWED_TOOLS = "Read Grep Glob Write Edit Bash(ls*)"
TOOLING_FILES = ("pyproject.toml", "package.json", ".pre-commit-config.yaml")
TOOLING_LINES = 60

BRIEFS: dict[str, str] = {
    "testing-infrastructure": (
        "testing infrastructure so an agent can change this repo safely: test "
        "runner and layout, markers/tiers, fakes at protocol boundaries, a "
        "tests-first gate, CI"
    ),
    "code-standards": (
        "types, formatting, linting and best practices from the recommendations, "
        "applied to this repo"
    ),
}


class ProposeError(Exception):
    """The change did not validate after a repair round; its files are left
    in `openspec/changes/<change>/` for a person to finish."""


def change_name(repo_name: str, kind: Kind) -> str:
    return f"{repo_name}-{kind}"


# --- the prompt -------------------------------------------------------------------


def _head(path: Path, lines: int = TOOLING_LINES) -> str:
    try:
        text = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    shown = "\n".join(text[:lines])
    if len(text) > lines:
        shown += f"\n… ({len(text) - lines} more lines)"
    return shown


def repo_summary(detection: RepoDetection) -> str:
    root = detection.path
    entries = []
    for child in sorted(root.iterdir()):
        if child.name in (".git", "node_modules", ".venv", "__pycache__"):
            continue
        entries.append(f"{child.name}/" if child.is_dir() else child.name)
    parts = [
        f"Path: {root}",
        f"Languages: {', '.join(detection.languages) or 'none detected'}",
        f"Has code: {'yes' if detection.has_code else 'no — an empty or docs-only repo'}",
        f"Service directories: {', '.join(detection.service_dirs) or 'none'}",
        f"Projects: {', '.join(project.path for project in detection.projects) or 'none'}",
        "Top level:\n" + "\n".join(f"  {entry}" for entry in entries),
    ]
    # Every project's tooling, not just the root's: a repo can keep its
    # pyproject.toml two levels down with a web app beside it, and a summary
    # built from the root alone describes none of it.
    searched = [root, *(root / project.path for project in detection.projects)]
    tooling = [directory / name for directory in dict.fromkeys(searched) for name in TOOLING_FILES]
    tooling += sorted((root / ".github" / "workflows").glob("*.y*ml"))
    for path in tooling:
        if path.is_file():
            relative = path.relative_to(root)
            parts.append(f"{relative} (first {TOOLING_LINES} lines):\n```\n{_head(path)}\n```")
    return "\n\n".join(parts)


PROMPT = """\
You are writing an OpenSpec change in this planning repo for the `{repo}` repo, \
which is mounted read-only at {repo_path}. Write nothing outside \
`openspec/changes/{change}/`.

The change: {brief}.

Create these files under `openspec/changes/{change}/`:
- `proposal.md` — `## Why`, `## What Changes`, `## Impact`.
- `design.md` — `## Context`, `## Decisions`; name the test harness, and \
call out any task group crossing a service boundary.
- `specs/<capability>/spec.md` — one per capability, as a delta spec: \
`## ADDED Requirements`, each `### Requirement: <name>` with a SHALL \
statement and at least one `#### Scenario: <name>` written as GIVEN / WHEN / \
THEN bullets.
- `tasks.md` — task groups under the heading contract below.

The heading contract, checked mechanically by `abk tags` after you finish:
`## <n>. [<repo>] [<tier>] <title>` — <repo> is `{repo}` (the workspace \
repos are {repos}), <tier> is tier1 or tier2, an optional third tag is \
[contract], [narrow] or [acceptance]. Groups are numbered from 1 in build \
order; each has tasks as `- [ ] <n>.<m> <task>` lines. Test tasks come before \
implementation tasks in every group. The last group is `[tier2] [acceptance]` \
and drives what the change built the way its consumer does — or, if there is \
nothing to drive, `tasks.md` contains a line `Acceptance: none — <reason>`.

Rules the authoring model in this workspace follows (from openspec/config.yaml):

{rules}

The repo, as detected:

{summary}

The tooling recommendations for its language, which the change applies:

{recommendations}

`openspec validate --strict` and `abk tags` are run on the result. Keep the \
change buildable in a few PRs: name concrete files, and prefer the repo's \
existing tools over new ones where the recommendations allow.
"""

REPAIR = """\

A previous attempt wrote `openspec/changes/{change}/`, and validation failed:

{errors}

Fix the files in place so both checks pass. Do not start over.
"""


def build_prompt(
    repo_name: str,
    detection: RepoDetection,
    *,
    change: str,
    kind: Kind,
    recommendations: str,
    repos: tuple[str, ...],
) -> str:
    return PROMPT.format(
        repo=repo_name,
        repo_path=detection.path,
        change=change,
        brief=BRIEFS[kind],
        repos=", ".join(repos),
        rules=render_rules(list(repos)),
        summary=repo_summary(detection),
        recommendations=recommendations.strip() or "(no recommendations document yet)",
    )


# --- fencing ------------------------------------------------------------------------


def _policy() -> ToolPolicy:
    """The policy hook, with writes fenced to the planning repo.

    A build agent's specs directory is read-only, which is right for it: its
    unit lives in a code repo's worktree and the spec is not its to change.
    Here the agent's whole job is to write a change under `openspec/changes/`,
    so that one restriction is dropped and the rest — the command policy, and
    writes confined to the checkout it runs in, which is the planning repo —
    stays.
    """
    return ToolPolicy(specs_dir=None, branch_prefix=active().github.branch_prefix)


# --- validation ---------------------------------------------------------------------


def validation_errors(
    planning: Path,
    change: str,
    *,
    repos: tuple[str, ...],
    run_openspec: openspec.Run | None = None,
    specs_dir: str = "openspec",
) -> list[str]:
    """Why `change` is not ready to be built, or an empty list.

    `specs_dir` is where the workspace keeps its OpenSpec store; `abk.yaml` can
    move it, and a check that assumes `openspec/` would call every change in
    such a workspace missing its tasks.
    """
    errors: list[str] = []
    result = openspec.validate(planning, run=run_openspec)
    try:
        report = json.loads(result.stdout or "{}")
    except ValueError:
        report = None
    if not isinstance(report, dict):
        errors.append(
            f"openspec validate exited {result.returncode} without a JSON report: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    else:
        items = [item for item in report.get("items", []) if item.get("id") == change]
        if not items:
            errors.append(f"openspec validate did not report a change named {change}")
        for item in items:
            if item.get("valid"):
                continue
            issues = item.get("issues") or []
            if not issues:
                errors.append(f"openspec: {change} is not valid")
            for issue in issues:
                if isinstance(issue, dict):
                    issue = issue.get("message", json.dumps(issue))
                errors.append(f"openspec: {issue}")

    tasks = planning / specs_dir / "changes" / change / "tasks.md"
    if not tasks.is_file():
        errors.append(f"{tasks.relative_to(planning)} is missing")
    else:
        _groups, tag_errors = validate_tasks(tasks, repos=repos)
        errors.extend(f"tasks.md line {error.line}: {error.message}" for error in tag_errors)
    return errors


# --- the step -------------------------------------------------------------------------


def propose(
    repo_name: str,
    detection: RepoDetection,
    *,
    planning: Path,
    recommendations: Path,
    kind: Kind,
    run_claude: RunClaude | None = None,
    run_openspec: openspec.Run | None = None,
    repos: tuple[str, ...] | None = None,
    runtime: AgentRuntime | None = None,
) -> str:
    """Write the change and return its name, or raise `ProposeError`."""
    workspace_repos = repos or (repo_name,)
    change = change_name(repo_name, kind)
    text = recommendations.read_text() if recommendations.is_file() else ""
    prompt = build_prompt(
        repo_name,
        detection,
        change=change,
        kind=kind,
        recommendations=text,
        repos=workspace_repos,
    )
    return write_change(
        prompt,
        planning=planning,
        change=change,
        reads=(detection.path,),
        repos=workspace_repos,
        run_claude=run_claude,
        run_openspec=run_openspec,
        runtime=runtime,
    )


def write_change(
    prompt: str,
    *,
    planning: Path,
    change: str,
    reads: tuple[Path, ...] = (),
    repos: tuple[str, ...],
    run_claude: RunClaude | None = None,
    run_openspec: openspec.Run | None = None,
    runtime: AgentRuntime | None = None,
) -> str:
    """Drive a model to write one change, validate it, repair once, or raise.

    Shared by `abk init` and the `propose` track, because the interesting part
    is not the prompt: it is that a change nobody validated is worse than no
    change at all. The pipeline reads `tasks.md` and nothing else about a
    change, so a mistagged group or an invalid spec becomes a unit that cannot
    be planned, discovered a tick later with no author present.

    `reads` are directories the model may read beyond the planning repo — the
    checkouts it is proposing work in. It writes only under `planning`.
    """
    agent = runtime_for(run_claude, runtime)

    def attempt(full_prompt: str) -> list[str]:
        succeeded(
            agent.run(
                AgentRequest(
                    prompt=full_prompt,
                    cwd=planning,
                    add_dirs=reads,
                    allowed_tools=ALLOWED_TOOLS,
                    permission_mode="edit",
                    policy=_policy(),
                )
            )
        )
        return validation_errors(planning, change, repos=repos, run_openspec=run_openspec)

    errors = attempt(prompt)
    if errors:
        errors = attempt(prompt + REPAIR.format(change=change, errors="\n".join(errors)))
    if errors:
        raise ProposeError(
            f"{change} did not validate after a repair round; its files are left in "
            f"openspec/changes/{change}/ to finish by hand:\n" + "\n".join(errors)
        )
    return change
