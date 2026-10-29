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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from agent_build_kit import openspec
from agent_build_kit.config import CONFIG_FILENAME, active
from agent_build_kit.init.claude_call import RunClaude, runtime_for, succeeded
from agent_build_kit.init.detect import RepoDetection
from agent_build_kit.init.scaffold import render_rules
from agent_build_kit.installation import changes_dir_under
from agent_build_kit.path_discovery import find_up
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.pipeline.work_graph import TaskGroup, project_tags, validate_tasks
from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.base import AgentRuntime

Kind = Literal["testing-infrastructure", "code-standards"]

ALLOWED_TOOLS = "Read Grep Glob Write Edit Bash(ls*)"
TOOLING_FILES = ("pyproject.toml", "package.json", ".pre-commit-config.yaml")
TOOLING_LINES = 60

BRIEFS: dict[str, str] = {
    "testing-infrastructure": (
        "testing infrastructure so an agent can change this repo safely: test "
        "runner and layout, markers and kinds of test, fakes at protocol boundaries, a "
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
    # The nearest file of each name from each, so one in a folder between the root and a
    # project is found too.
    found = (
        find_up([name], directory, stop=root, accept=Path.is_file)
        for directory in dict.fromkeys(searched)
        for name in TOOLING_FILES
    )
    tooling = list(dict.fromkeys(path for path in found if path is not None))
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
`## <n>. [<repo>] [<kind>] <title>` — <repo> is `{repo}` (the workspace \
repos are {repos}), <kind> is `unit-test`, `integration-test` or `e2e-test` \
(the old spellings are still read), an optional third tag is [contract], [narrow] \
or [acceptance]. Groups are numbered from 1 in build order; \
each has tasks as `- [ ] <n>.<m> <task>` lines. Test tasks come before \
implementation tasks in every group. The last group is `[e2e-test] [acceptance]` \
and drives what the change built the way its consumer does — or, if there is \
nothing to drive, `tasks.md` contains a line `Acceptance: none — <reason>`.

The three kinds of test a group can need: `unit-test` is the ordinary suite, \
run anywhere; `integration-test` covers behaviour across modules in the ordinary \
suite with no live stack, and is not the `integration` marker or \
`tests/integration/`; `e2e-test` needs the real local stack. The `[acceptance]` \
tag is for `e2e-test` only.

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


def _policy(planning: Path) -> ToolPolicy:
    """The policy hook, with writes fenced to the planning repo.

    A build agent's specs directory is read-only, which is right for it: its
    unit lives in a code repo's worktree and the spec is not its to change.
    Here the agent's whole job is to write a change under `openspec/changes/`,
    so that one restriction is dropped and the rest — the command policy, and
    writes confined to the checkout it runs in, which is the planning repo —
    stays. The review policy in abk.yaml is a person's, so no command writes it.
    """
    return ToolPolicy(
        specs_dir=None,
        branch_prefix=active().git.branch_prefix,
        fenced_files=(planning / CONFIG_FILENAME,),
    )


# --- validation ---------------------------------------------------------------------


def validation_errors(
    planning: Path,
    change: str,
    *,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
    splits: Mapping[str, tuple[str, ...]] | None = None,
    run_openspec: openspec.Run | None = None,
    specs_dir: str = "openspec",
) -> list[str]:
    """Why `change` is not ready to be built, or an empty list."""
    return validation_report(
        planning,
        change,
        repos=repos,
        projects=projects,
        splits=splits,
        run_openspec=run_openspec,
        specs_dir=specs_dir,
    )[1]


def validation_report(
    planning: Path,
    change: str,
    *,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
    splits: Mapping[str, tuple[str, ...]] | None = None,
    run_openspec: openspec.Run | None = None,
    specs_dir: str = "openspec",
) -> tuple[list[TaskGroup], list[str]]:
    """The groups of `change`'s tasks that could be read, and why the change is not ready to be
    built (an empty list when it is).

    `specs_dir` is where the workspace keeps its OpenSpec store; `abk.yaml` can
    move it, and a check that assumes `openspec/` would call every change in
    such a workspace missing its tasks.
    """
    errors: list[str] = []
    groups: list[TaskGroup] = []
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

    tasks = changes_dir_under(planning, specs_dir) / change / "tasks.md"
    if not tasks.is_file():
        errors.append(f"{tasks.relative_to(planning)} is missing")
    else:
        # Without `splits`, a workspace being set up declares no e2e-test splits yet, so only
        # `rest` is accepted.
        groups, tag_errors = validate_tasks(
            tasks, repos=repos, projects=projects, splits={} if splits is None else splits
        )
        errors.extend(f"tasks.md line {error.line}: {error.message}" for error in tag_errors)
    return groups, errors


def repair_once(
    attempt: Callable[[str], list[str]], prompt: str, repair: Callable[[list[str]], str]
) -> list[str]:
    """Run `attempt` on `prompt`; when it finds errors, run it once more on `prompt` followed by
    `repair` of them. The errors still found, or an empty list. An attempt that cannot be
    repaired answers an empty list, which ends it."""
    errors = attempt(prompt)
    if errors:
        errors = attempt(prompt + repair(errors))
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
    projects: Mapping[str, tuple[str, ...]] | None = None,
    runtime: AgentRuntime | None = None,
) -> str:
    """Write the change and return its name, or raise `ProposeError`. `projects` are the
    projects each repo declares beside its root; the detected ones of `repo_name` when unsaid."""
    workspace_repos = repos or (repo_name,)
    workspace_projects = (
        projects if projects is not None else {repo_name: project_tags(detection.projects)}
    )
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
        projects=workspace_projects,
        run_claude=run_claude,
        run_openspec=run_openspec,
        runtime=runtime,
        repo=repo_name,
    )


def write_change(
    prompt: str,
    *,
    planning: Path,
    change: str,
    reads: tuple[Path, ...] = (),
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
    run_claude: RunClaude | None = None,
    run_openspec: openspec.Run | None = None,
    runtime: AgentRuntime | None = None,
    repo: str = "",
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
        request = recorded(
            AgentRequest(
                prompt=full_prompt,
                cwd=planning,
                add_dirs=reads,
                allowed_tools=ALLOWED_TOOLS,
                permission_mode="edit",
                policy=_policy(planning),
            ),
            agent,
            node=OverheadNode.INIT_PROPOSE,
            change=change,
            repo=repo,
            say=print,
        )
        succeeded(agent.run(request))
        return validation_errors(
            planning, change, repos=repos, projects=projects, run_openspec=run_openspec
        )

    errors = repair_once(
        attempt, prompt, lambda found: REPAIR.format(change=change, errors="\n".join(found))
    )
    if errors:
        raise ProposeError(
            f"{change} did not validate after a repair round; its files are left in "
            f"openspec/changes/{change}/ to finish by hand:\n" + "\n".join(errors)
        )
    return change
