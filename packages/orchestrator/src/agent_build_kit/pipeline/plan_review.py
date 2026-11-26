"""A model reads a change's plan before its first unit starts; a blocker finding holds the change.

The four questions the model is asked are `QUESTIONS`, in order: a finding names its question
by the number (from 1) of the one it answers. Each question is asked in its own pass, with
read-only tools over each repo's default branch, so the first review finds as much as it can. A
finding is a `blocker` (a unit would end red, or a task cannot be built) or `advice` (wording, an
installation matter, something the reviewer could not check); only a blocker holds.

A review is recorded with a hash of what it read (the change's artifacts and its planned units),
and a change whose hash has a review is not reviewed again. Every review is fresh: the model is
never shown earlier findings. What a person decided is kept outside the model: a finding a person
cleared is not raised again while its group's text is unchanged.

A blocker that names a fix is repaired before it holds: the plan model rewrites `tasks.md` with
the fixes, the rewrite is kept only when every group heading is unchanged and the tasks still
validate, it is committed to the planning repo, and the change is reviewed again, at most
`planning.plan_review_repairs` times per change. What is left holds the change's units that have
not started; a started unit is never held. A review that fails holds nothing and is logged, so the
review can never stop the pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, TypeVar

from agent_build_kit import __version__, runtimes, skills
from agent_build_kit.config import models
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import shell, spans
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.planner import PlannerError, ask_plan_model
from agent_build_kit.pipeline.planning_commit import commit_and_publish
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import BUILDS_NOTHING, FINISHED_STATES, IN_REVIEW, MERGED
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.pipeline.work_graph import (
    group_needs,
    specification_text,
    validate_tasks,
    validate_tasks_text,
)
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import PromptTooLarge, check_prompt_size

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# The fixed questions every review asks, in the order a finding numbers them.
QUESTIONS: tuple[str, ...] = (
    "Does each unit end with the suite green, given what its groups move, rename or delete?",
    "Does any task need live numbers, an installation edit or an edit to the change's own files?",
    "Can each `Check:` run in the check environment?",
    "Does a later group's test assert something an earlier unit already broke?",
)

RECORD = "plan_reviews.json"
ARTIFACTS = ("proposal.md", "design.md")

# What the reviewer may run: reads only, and git commands that read a branch without a checkout.
REVIEW_TOOLS = (
    "Read Grep Glob Bash(git show*) Bash(git ls-tree*) Bash(git grep*) Bash(git log*) "
    "Bash(git diff*)"
)

PROMPT = """You are reviewing the plan of the change `{change}` before its first unit is built.
Read the change's artifacts and its planned units below, and answer this one question for every
group:

{number}. {question}

You may read the repositories yourself. Each repo's checkout is listed below with its default
branch; read what is on that branch, not the working tree (`git show <branch>:<path>`, `git
ls-tree -r --name-only <branch> -- <folder>`, `git grep <pattern> <branch> -- <path>`). Files the
change will create do not exist yet, by design. Before you say a file, test or setting is missing,
look for it. A change's groups are built in order, each on the one before, unless a group carries
an `Independent:` line: a group never needs a `Needs:` line on a group of its own change, and
`abk tags` refuses one.

Repositories:
{repos}

The mechanical checks already report the following for this change. Do not repeat it:
{report}

The change's units, in the order they are built. Each line says its state: the groups of a
`merged` unit are on the default branch already, and an `in_review` unit's groups are on its branch
with the pull request named. Judge each group against what the units before it leave, not
against the order units happen to be listed elsewhere.
{units}

Files the tasks name, as they stand on each repo's default branch:
{repository}

Changes in this change's `Needs:` chain (the changes it names in `Needs:` lines and the changes
that name it, followed through each other), nearest first, with the test and support paths their
tasks name. A path whose convention (the folder tests live in, how files are named) differs from
the chain's is a finding on the group that names it: a blocker when a unit would end red,
otherwise advice, and its fix names the chain's convention. Never invent a second convention.
{chain}

Rules the plan follows: the shipped authoring rules every task follows, then each repository's own
guidance file as it stands on its default branch. The plan's paths and tasks must agree with them;
one that does not is a finding on the group that has it, and its fix names the rule.
{rules}

Artifacts:
{artifacts}

Answer with a short reading, then one JSON object on its own, `{{"findings": [...]}}`. Each
finding is `{{"group": <group number>, "question": {number}, "kind": "blocker" | "advice",
"evidence": "<what you found, naming the files>", "fix": "<the edit to tasks.md that resolves
it, or empty>"}}`. A `blocker` is something that will make a unit end red or a task impossible to
build as written. Everything else is `advice`: wording, an installation or machine matter that
tasks.md cannot fix, or something you could not check. Report only what you can show;
`{{"findings": []}}` when the plan can work.
"""

REPAIR_PROMPT = """The plan of the change `{change}` has review findings that will make a unit
fail. Rewrite its tasks.md so that each finding below is resolved, using the fix it names. Change
only what the findings need: keep every group heading line exactly as it is, keep every other
group and task as written, and follow the rules the file already follows.

Findings:
{findings}

The current tasks.md:
<<<TASKS
{tasks}
TASKS>>>

Answer with the whole new tasks.md between the same markers, `<<<TASKS` and `TASKS>>>`, and
nothing between them but the file.
"""

# A failed review is asked again after this long, at most `MAX_ATTEMPTS` times for one plan; a
# prompt that was too large is not asked again until the plan changes.
RETRY_AFTER = timedelta(hours=1)
MAX_ATTEMPTS = 3
# The most bytes of the repository's files the request carries, and of any one file. The reviewer
# reads the rest itself.
VIEW_BUDGET = 60_000
VIEW_FILE_LIMIT = 12_000
# The most bytes of the `Needs:` chain's listing the request carries, and of paths for any one
# change in it.
CHAIN_BUDGET = 8_000
CHAIN_CHANGE_LIMIT = 30
# The section of the shipped authoring skill the request carries, and the most characters of it and
# of any one repository's guidance file.
AUTHORING_RULES_SECTION = "Rules every task follows"
AUTHORING_RULES_LIMIT = 12_000
REPO_RULES_LIMIT = 12_000
# A repository's guidance file, the first that is committed at its default branch.
GUIDANCE_FILES = ("AGENTS.md", "CLAUDE.md")

Kind = Literal["blocker", "advice"]


class Finding(Frozen):
    """One thing a review found: the group, the question (from 1), whether it holds the change,
    the evidence, and the edit to tasks.md that would resolve it."""

    group: int
    question: int
    evidence: str
    # A finding recorded before kinds existed was a hold.
    kind: Kind = "blocker"
    fix: str = ""


class Kept(Frozen):
    """A finding a person cleared, and the text of its group when they did: the same finding is
    not raised again while that text stands."""

    group: int
    question: int
    group_text: str
    note: str = ""


class Review(Frozen):
    """What a review of one plan recorded. A cleared review keeps its findings and its note."""

    hash: str
    findings: tuple[Finding, ...] = ()
    cleared: bool = False
    note: str = ""
    # A review that failed holds nothing: it records the error, when, and how many times this
    # plan has been asked, so the same plan is not asked on every tick.
    error: str = ""
    attempts: int = 0
    failed_at: datetime | None = None
    permanent: bool = False
    # Carried from review to review of the change: what people cleared, and how many repairs
    # the pipeline has made to its tasks.md.
    kept: tuple[Kept, ...] = ()
    repairs: int = 0

    @property
    def blockers(self) -> tuple[Finding, ...]:
        return tuple(found for found in self.findings if found.kind == "blocker")

    @property
    def holds(self) -> bool:
        return bool(self.blockers) and not self.cleared

    @property
    def failed(self) -> bool:
        return bool(self.error)

    def retry_due(self, now: datetime) -> bool:
        """Whether a failed review of this plan is to be asked again at `now`."""
        if self.permanent or self.attempts >= MAX_ATTEMPTS or self.failed_at is None:
            return False
        return now - self.failed_at >= RETRY_AFTER


class Unreadable(ValueError):
    """The model's answer held no findings that could be read."""


def record_path(inst: Installation) -> Path:
    return inst.state_dir / RECORD


def read_reviews(path: Path) -> dict[str, Review]:
    """Every change's recorded review; none when the file is missing. A file that cannot be
    read is logged, and `_record` keeps a copy of it beside the new one."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return {}
    except OSError as error:
        logger.warning("plan reviews: %s cannot be read: %s", path, error)
        return {}
    try:
        raw = json.loads(text)
        return {change: Review.model_validate(entry) for change, entry in raw.items()}
    except (ValueError, AttributeError) as error:
        logger.warning("plan reviews: %s cannot be parsed: %s", path, error)
        return {}


def _write(path: Path, reviews: Mapping[str, Review]) -> None:
    body = {change: review.model_dump(mode="json") for change, review in reviews.items()}
    atomic_write_text(path, json.dumps(body, indent=2, sort_keys=True) + "\n")


def _record(path: Path, change: str, review: Review) -> None:
    with file_lock(path.with_name(f"{path.name}.lock")):
        reviews = read_reviews(path)
        if not reviews and path.is_file() and path.stat().st_size:
            shutil.copyfile(path, path.with_name(f"{path.name}.unreadable"))
        reviews[change] = review
        _write(path, reviews)


def held_changes(inst: Installation) -> dict[str, Review]:
    """The changes whose review has blocker findings no person has cleared, each with its
    review. They hold only the change's units that have not started."""
    return {
        change: review for change, review in read_reviews(record_path(inst)).items() if review.holds
    }


def group_texts(tasks: Path) -> dict[int, str]:
    """Each group's heading and lines with progress stripped, by number: what a person's clear
    of a finding on that group is kept against."""
    try:
        groups, _ = validate_tasks(tasks)
    except (OSError, ValueError):
        return {}
    return {
        group.number: "\n".join(
            re.sub(r"^(\s*- )\[[xX]\]", r"\1[ ]", line) for line in (group.title, *group.body)
        ).strip()
        for group in groups
    }


def clear(inst: Installation, change: str, note: str = "") -> int:
    """Clear the findings standing on `change`, keeping them and `note` with the review, and
    keep each so the same finding is not raised again while its group's text stands; return how
    many were cleared (none when no finding stood)."""
    path = record_path(inst)
    texts = group_texts(inst.changes_dir / change / "tasks.md")
    with file_lock(path.with_name(f"{path.name}.lock")):
        reviews = read_reviews(path)
        review = reviews.get(change)
        if review is None or not review.holds:
            return 0
        kept = _merge_kept(
            review.kept,
            (
                Kept(
                    group=found.group,
                    question=found.question,
                    group_text=texts.get(found.group, ""),
                    note=note,
                )
                for found in review.findings
            ),
        )
        reviews[change] = review.model_copy(update={"cleared": True, "note": note, "kept": kept})
        _write(path, reviews)
        return len(review.blockers)


def _merge_kept(earlier: Sequence[Kept], added: Iterable[Kept]) -> tuple[Kept, ...]:
    """`earlier` with `added`, one entry per group and question, the newest winning."""
    merged = {(entry.group, entry.question): entry for entry in earlier}
    merged.update({(entry.group, entry.question): entry for entry in added})
    return tuple(merged[key] for key in sorted(merged))


def _not_kept(
    findings: Sequence[Finding], kept: Sequence[Kept], texts: Mapping[int, str]
) -> tuple[Finding, ...]:
    """The findings no person has already cleared on a group whose text still stands."""
    standing = {
        (entry.group, entry.question)
        for entry in kept
        if entry.group_text and texts.get(entry.group) == entry.group_text
    }
    return tuple(found for found in findings if (found.group, found.question) not in standing)


def finding_lines(review: Review) -> list[str]:
    """One line per finding, as `show` and `abk status` print them."""
    return [
        f"group {found.group}, question {found.question} ({found.kind}): {found.evidence}"
        + (f" Fix: {found.fix}" if found.fix else "")
        for found in review.findings
    ]


def _artifacts(folder: Path, *, tasks: bool = True) -> str:
    paths = [folder / name for name in ARTIFACTS]
    paths += sorted((folder / "specs").glob("**/spec.md"))
    if tasks:
        paths.append(folder / "tasks.md")
    return "\n\n".join(
        f"### {path.relative_to(folder)}\n{path.read_text()}" for path in paths if path.is_file()
    )


def _path_names(body: Sequence[str]) -> list[str]:
    """The backticked path-like names in a group's lines, in order, once each: a name with a
    folder, or a file name with an extension at a repo's root (`config.yaml`)."""
    found = (name for line in body for name in re.findall(r"`([^`\s]+)`", line))
    pathlike = (
        name
        for name in found
        if ("/" in name or re.fullmatch(r"[\w.-]+\.\w+", name)) and not re.search(r"[*$<>{}]", name)
    )
    return list(dict.fromkeys(pathlike))


def repository_view(inst: Installation, tasks: Path) -> str:
    """A read-only view of the repository: for each group, the paths its lines name that exist at
    its repo's default branch, with their content, read through git within `VIEW_BUDGET`."""
    try:
        groups, _ = validate_tasks(tasks)
    except (OSError, ValueError):
        return "(the tasks could not be read)"
    sections: list[str] = []
    seen: set[tuple[str, str]] = set()
    left = VIEW_BUDGET
    for group in groups:
        try:
            repo = inst.repo(group.repo)
        except KeyError:
            continue
        for name in _path_names((group.title, *group.body)):
            if (group.repo, name) in seen or left <= 0:
                continue
            seen.add((group.repo, name))
            try:
                shown = shell.git(repo.path, "show", f"{repo.default_branch}:{name}", check=False)
            except OSError:
                continue
            if shown.returncode:
                continue
            content = shown.stdout[: min(VIEW_FILE_LIMIT, left)]
            left -= len(content.encode())
            sections.append(f"#### {group.repo}:{name}\n{content}")
    return "\n\n".join(sections) or "(none of the named paths exist there)"


def _repo_checkouts(inst: Installation, tasks: Path) -> list[tuple[str, Path, str]]:
    """The repos the change's groups name, each with its checkout and default branch."""
    try:
        groups, _ = validate_tasks(tasks)
    except (OSError, ValueError):
        return []
    found: dict[str, tuple[str, Path, str]] = {}
    for group in groups:
        try:
            repo = inst.repo(group.repo)
        except KeyError:
            continue
        found.setdefault(group.repo, (group.repo, Path(repo.path), repo.default_branch))
    return list(found.values())


def _needed(path: Path) -> set[str]:
    """The changes the groups of the tasks file at `path` name in `Needs:` lines."""
    try:
        return {need.change for needs in group_needs(path).values() for need in needs}
    except OSError:
        return set()


def _is_test_path(name: str) -> bool:
    parts = name.split("/")
    base = parts[-1]
    return (
        any(part in ("tests", "test") for part in parts[:-1])
        or base.startswith("test_")
        or re.search(r"_test\.\w+$|\.(test|spec)\.\w+$", base) is not None
    )


def _is_support_path(name: str) -> bool:
    parts = name.split("/")
    return "fixtures" in parts[:-1] or parts[-1] == "conftest.py"


def _chain_paths(text: str) -> list[str]:
    """The test and support paths a tasks file names, once each, each with its group's repo."""
    found: list[str] = []
    repo = ""
    for line in text.splitlines():
        if heading := re.match(r"##\s+\d+\.\s+\[([^\]]+)\]", line):
            repo = heading.group(1)
        on_support = line.strip().startswith("Support:")
        for name in _path_names((line,)):
            if on_support or _is_test_path(name) or _is_support_path(name):
                found.append(f"{repo}:{name}")
    return list(dict.fromkeys(found))


def _distances(start: str, edges: Mapping[str, set[str]]) -> dict[str, int]:
    """Steps from `start` to each change reachable along `edges`."""
    seen: dict[str, int] = {}
    frontier = [start]
    steps = 0
    while frontier:
        steps += 1
        following: list[str] = []
        for name in frontier:
            for other in sorted(edges.get(name, ())):
                if other != start and other not in seen:
                    seen[other] = steps
                    following.append(other)
        frontier = following
    return seen


def chain_listing(inst: Installation, tasks: Path) -> str:
    """The changes in the `Needs:` chain of the change whose tasks file is `tasks`, nearest first
    then by name, each with its title and its test and support paths, cut to `CHAIN_BUDGET` (and
    `CHAIN_CHANGE_LIMIT` paths a change); the changes left out are named. Empty without a chain."""
    me = tasks.parent.name
    files = {path.parent.name: path for path in inst.tasks_files()}
    named = {name: _needed(path) & files.keys() - {name} for name, path in files.items()}
    named_by: dict[str, set[str]] = {}
    for name, others in named.items():
        for other in others:
            named_by.setdefault(other, set()).add(name)
    nearest: dict[str, int] = {}
    for edges in (named, named_by):
        for name, steps in _distances(me, edges).items():
            nearest[name] = min(steps, nearest.get(name, steps))
    left = CHAIN_BUDGET
    shown: list[str] = []
    skipped: list[str] = []
    for name in sorted(nearest, key=lambda n: (nearest[n], n)):
        try:
            text = files[name].read_text()
        except OSError:
            continue
        title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), "")
        paths = _chain_paths(text)
        lines = [f"### {name} — {title}", *(f"- {p}" for p in paths[:CHAIN_CHANGE_LIMIT])]
        if len(paths) > CHAIN_CHANGE_LIMIT:
            lines.append(f"- (and {len(paths) - CHAIN_CHANGE_LIMIT} more)")
        entry = "\n".join(lines)
        if skipped or len(entry.encode()) > left:
            skipped.append(name)
            continue
        left -= len(entry.encode()) + 1
        shown.append(entry)
    if skipped:
        shown.append(f"not listed, over the size limit: {', '.join(skipped)}")
    return "\n".join(shown)


def skill_section(text: str, section: str) -> str:
    """The body of the `## <section>` part of a skill's text, cut to `AUTHORING_RULES_LIMIT`
    with a note naming the skill; `(none)` when the text has no such section."""
    lines = text.splitlines()
    heading = f"## {section}"
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return "(none)"
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"#{1,2} ", lines[i])), len(lines)
    )
    body = "\n".join(lines[start + 1 : end]).strip()
    if len(body) > AUTHORING_RULES_LIMIT:
        body = (
            body[:AUTHORING_RULES_LIMIT]
            + f"\n[cut at the size limit: the rest is in the abk-authoring skill, {section}]"
        )
    return body


def rules_listing(inst: Installation, tasks: Path) -> str:
    """The rules a request carries: the shipped authoring rules under a line naming the skill and
    its version, then each repo the change names with its first committed guidance file
    (`AGENTS.md`, else `CLAUDE.md`) at its default branch, cut to `REPO_RULES_LIMIT`."""
    shipped = skill_section(skills.source("abk-authoring"), AUTHORING_RULES_SECTION)
    parts = [
        f"#### abk-authoring skill, version {__version__}, section {AUTHORING_RULES_SECTION}\n"
        + shipped
    ]
    for name, path, branch in _repo_checkouts(inst, tasks):
        found = ("(none)", "")
        for file in GUIDANCE_FILES:
            try:
                shown = shell.git(path, "show", f"{branch}:{file}", check=False)
            except OSError:
                continue
            if shown.returncode == 0:
                found = (file, shown.stdout)
                break
        file, content = found
        body = content[:REPO_RULES_LIMIT]
        if len(content) > REPO_RULES_LIMIT:
            body += f"\n[cut at the size limit: the rest of {file} is in the repository]"
        parts.append(f"#### {name}: {file} at {branch}\n{body}".rstrip())
    return "\n\n".join(parts)


def _unit_line(unit: StoredUnit) -> str:
    groups = ", ".join(
        f"{member.change} group {number}" for member in unit.members() for number in member.groups
    )
    state = str(unit.state)
    if unit.pr is not None and unit.state in (IN_REVIEW, MERGED):
        state += f", pull request {unit.pr}"
    return f"- {unit.id} [{unit.repo}, {unit.tier}] ({groups}) {state}: {unit.title}"


def _first_group(unit: StoredUnit, change: str) -> int:
    numbers = [n for member in unit.members() if member.change == change for n in member.groups]
    return min(numbers, default=0)


def build_order(units: Sequence[StoredUnit], change: str) -> list[StoredUnit]:
    """The units of `change` a review is shown, merged ones included, in the order they are built:
    a unit after every unit of the change it depends on, and otherwise by its lowest group of the
    change. A retired or unplanned unit builds nothing and is left out."""
    mine = {
        unit.id: unit
        for unit in units
        if unit.change == change and unit.state not in BUILDS_NOTHING
    }
    placed: list[StoredUnit] = []
    done: set[str] = set()
    waiting = sorted(mine.values(), key=lambda unit: (_first_group(unit, change), unit.id))
    while waiting:
        ready = next(
            (u for u in waiting if all(d in done or d not in mine for d in u.depends_on)),
            waiting[0],  # a cycle cannot be planned; fall back to group order rather than stop
        )
        waiting.remove(ready)
        placed.append(ready)
        done.add(ready.id)
    return placed


def open_units(units: Sequence[StoredUnit], change: str) -> list[StoredUnit]:
    """The units of `change` still to be reviewed: planned, started or in review, not finished."""
    return [
        unit
        for unit in units
        if unit.change == change
        and unit.state not in FINISHED_STATES
        and unit.state not in BUILDS_NOTHING
    ]


def plan_hash(folder: Path, units: Sequence[StoredUnit]) -> str:
    """A hash of what the change asks for and how it was planned: its artifacts, its tasks with
    progress stripped (what the planner keys on), and its units by id and groups whatever their
    state. A unit landing, a ticked box or a tier review raises changes none of it."""
    tasks = folder / "tasks.md"
    asked = specification_text(tasks.read_text()) if tasks.is_file() else ""
    planned = sorted(
        f"{unit.id}:{','.join(str(n) for member in unit.members() for n in member.groups)}"
        for unit in units
    )
    text = _artifacts(folder, tasks=False) + "\n" + asked + "\n" + "\n".join(planned)
    return hashlib.sha256(text.encode()).hexdigest()


def build_prompt(
    change: str,
    folder: Path,
    units: Sequence[StoredUnit],
    report: Sequence[str],
    repository: str = "",
    *,
    question: int = 1,
    repos: Sequence[tuple[str, Path, str]] = (),
    chain: str = "",
    rules: str = "",
) -> str:
    """The request for one question: the question, the repos to read, the artifacts, the units
    and the mechanical checks' report."""
    return PROMPT.format(
        change=change,
        number=question,
        question=QUESTIONS[question - 1],
        repos="\n".join(
            f"- {name}: {path} (default branch `{branch}`)" for name, path, branch in repos
        )
        or "(none)",
        report="\n".join(report) or "(nothing)",
        units="\n".join(_unit_line(unit) for unit in units),
        repository=repository or "(none)",
        chain=chain or "(none)",
        rules=rules or "(none)",
        artifacts=_artifacts(folder),
    )


def parse_findings(text: str) -> tuple[Finding, ...]:
    """The findings in a model's answer: the first JSON object with a `findings` list. Raises
    `Unreadable` when there is none or a finding is malformed."""
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            found, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(found, dict) and isinstance(found.get("findings"), list):
            try:
                findings = tuple(Finding.model_validate(item) for item in found["findings"])
            except ValueError as error:
                raise Unreadable(str(error)) from error
            if any(not 1 <= item.question <= len(QUESTIONS) for item in findings):
                raise Unreadable("a finding names a question that does not exist")
            return findings
    raise Unreadable("no findings object in the answer")


def ask_reviewer(
    prompt: str,
    *,
    change: str,
    planning_root: Path,
    checkouts: Sequence[Path],
    say: Callable[[str], None],
) -> str:
    """One review pass: the plan model, with read-only tools over the planning repo and the
    repos' checkouts. Raises `PlannerError` as the planner's call does."""
    agent = runtimes.active()
    request = recorded(
        AgentRequest(
            prompt=prompt,
            role="plan",
            change=change,
            cwd=planning_root,
            add_dirs=tuple(path for path in checkouts if path.is_dir()),
            model=models().plan or None,
            allowed_tools=REVIEW_TOOLS,
            permission_mode="allowed_tools_only",
        ),
        agent,
        node=OverheadNode.PLAN,
        change=change,
        say=say,
    )
    try:
        check_prompt_size(request, agent.prompt_transport)
    except PromptTooLarge as error:
        raise PlannerError(str(error)) from error
    result = agent.run(request)
    if not result.ok:
        raise PlannerError(f"the review call failed: {result.error}")
    return result.text


class _Stopped(Exception):
    """A call was not made, or was refused, and no further call is to start."""


class _Gate:
    """What the calls of one step share: the bound on calls in flight, the lock that makes
    repairs one at a time, and the first refusal (any error that is not a `PlannerError`), after
    which no further call starts."""

    def __init__(self, bound: int) -> None:
        self.slots = asyncio.Semaphore(bound)
        self.repairs = asyncio.Lock()
        self.refusal: Exception | None = None

    async def call(self, blocking: Callable[[], _T]) -> _T:
        """Run `blocking` in a thread once a slot is free. Raises `PlannerError` as it does and
        `_Stopped` when it was not started or was refused."""
        async with self.slots:
            if self.refusal is not None:
                raise _Stopped
            try:
                return await asyncio.to_thread(blocking)
            except PlannerError:
                raise
            except Exception as error:
                self.refusal = self.refusal or error
                raise _Stopped from error


async def _pass(
    gate: _Gate,
    number: int,
    *,
    inst: Installation,
    change: str,
    tasks: Path,
    mine: Sequence[StoredUnit],
    report: Sequence[str],
    view: str,
    repos: Sequence[tuple[str, Path, str]],
    chain: str,
    rules: str,
    say: Callable[[str], None],
) -> tuple[Finding, ...] | PlannerError | None:
    """One question's pass: its findings, the `PlannerError` it ended in, or None when it was
    stopped."""
    prompt = build_prompt(
        change,
        tasks.parent,
        mine,
        report,
        view,
        question=number,
        repos=repos,
        chain=chain,
        rules=rules,
    )
    try:
        answer = await gate.call(
            lambda: ask_reviewer(
                prompt,
                change=change,
                planning_root=inst.root,
                checkouts=[path for _, path, _ in repos],
                say=say,
            )
        )
        found = parse_findings(answer)
    except PlannerError as error:
        return error
    except Unreadable as error:
        return PlannerError(f"the answer could not be read: {error}")
    except _Stopped:
        return None
    # A pass answers one question; a finding it files under another is that pass's to find.
    return tuple(item for item in found if item.question == number)


async def _review_once(
    gate: _Gate,
    inst: Installation,
    change: str,
    tasks: Path,
    mine: Sequence[StoredUnit],
    report: Sequence[str],
    say: Callable[[str], None],
) -> tuple[Finding, ...] | PlannerError | None:
    """Every question asked in its own pass, together; the findings of all of them in question
    order, or the error of the lowest-numbered pass that failed. None when a call was stopped."""
    repos = _repo_checkouts(inst, tasks)
    view = repository_view(inst, tasks)
    chain = chain_listing(inst, tasks)
    rules = rules_listing(inst, tasks)
    async with asyncio.TaskGroup() as group:
        passes = [
            group.create_task(
                _pass(
                    gate,
                    number,
                    inst=inst,
                    change=change,
                    tasks=tasks,
                    mine=mine,
                    report=report,
                    view=view,
                    repos=repos,
                    chain=chain,
                    rules=rules,
                    say=say,
                )
            )
            for number in range(1, len(QUESTIONS) + 1)
        ]
    results = [one.result() for one in passes]
    if any(result is None for result in results):
        return None
    failed = next((result for result in results if isinstance(result, PlannerError)), None)
    if failed is not None:
        return failed
    return tuple(
        item
        for result in results
        if not isinstance(result, PlannerError) and result
        for item in result
    )


_TASKS_BLOCK = re.compile(r"<<<TASKS\n(.*?)\nTASKS>>>", re.DOTALL)


def _headings(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.startswith("## ")]


def repair(
    inst: Installation,
    change: str,
    tasks: Path,
    blockers: Sequence[Finding],
    *,
    say: Callable[[str], None],
) -> str:
    """Ask the plan model to rewrite `tasks` with the blockers' fixes, keep the rewrite when its
    group headings are unchanged and it validates, and commit it. Return "" when it was
    committed, or why it was not."""
    relative = tasks.relative_to(inst.root)
    dirty = shell.git(inst.root, "status", "--porcelain", "--", str(relative), check=False)
    if dirty.returncode or dirty.stdout.strip():
        return f"{relative} has edits that are not committed, so it is left as it is"
    before = tasks.read_text()
    prompt = REPAIR_PROMPT.format(
        change=change,
        findings="\n".join(
            f"- group {found.group}: {found.evidence} Fix: {found.fix}" for found in blockers
        ),
        tasks=before,
    )
    try:
        answer = ask_plan_model(prompt, change=change, say=say)
    except PlannerError as error:
        return f"the repair call failed: {error}"
    match = _TASKS_BLOCK.search(answer)
    if match is None:
        return "the repair answer held no tasks.md"
    after = match.group(1).rstrip() + "\n"
    if after == before:
        return "the repair changed nothing"
    if _headings(after) != _headings(before):
        return "the repair changed a group heading"
    _, errors = validate_tasks_text(after, change, repos=tuple(inst.repos))
    if errors:
        return "the repair does not validate: " + "; ".join(str(error) for error in errors[:3])
    tasks.write_text(after)
    fixed = ", ".join(sorted({f"group {found.group}" for found in blockers}))
    committed = commit_and_publish(
        inst,
        [str(relative)],
        message=f"plan({change}): repair the plan review's findings on {fixed}",
        label=f"plan-repair-{change}",
        body="abk repaired the blocker findings of the plan review:\n"
        + "\n".join(f"- group {found.group}: {found.fix}" for found in blockers),
        what=f"the repair of {change}",
        log=say,
    )
    if not committed:
        tasks.write_text(before)
        return "the repair could not be committed"
    return ""


def review_changes(
    inst: Installation,
    units: Sequence[StoredUnit],
    *,
    mechanical: Callable[[Path], list[str]],
    say: Callable[[str], None],
) -> None:
    """Review each change with open units whose plan has no review yet, most urgent first (the
    most urgent stored priority of its open units, ties by name), repair what it can, and
    record what is left. A review that fails is logged and holds nothing.

    The passes of a review and several changes run together, with at most
    `planning.plan_review_concurrency` review and repair calls in flight and the calls starting in
    the order of the changes' urgency. A call refused for usage (any error that is not a
    `PlannerError`) starts no further call; the calls in flight finish, the reviews whose calls
    all answered are recorded, and the refusal is raised. Each change's log lines are written
    together, in the order the reviews started. Not to be entered from a running event loop."""
    if not inst.config.planning.review_plans:
        return
    reviews = read_reviews(record_path(inst))
    due = [
        (min(unit.priority for unit in open_now), tasks)
        for tasks in inst.tasks_files()
        if (open_now := open_units(units, tasks.parent.name))
    ]
    ordered = [tasks for _, tasks in sorted(due, key=lambda item: (item[0], item[1].parent.name))]
    logs: list[list[str]] = [[] for _ in ordered]
    gate = _Gate(inst.config.planning.plan_review_concurrency)

    async def run_all() -> None:
        async with asyncio.TaskGroup() as group:
            for tasks, lines in zip(ordered, logs, strict=True):
                group.create_task(
                    _review_until_done(gate, inst, tasks, units, reviews, mechanical, lines.append)
                )

    try:
        asyncio.run(run_all())
    except ExceptionGroup as group:
        # The task group wraps what one change's review raised; the tick logs the real error.
        leaf: BaseException = group
        while isinstance(leaf, ExceptionGroup):
            leaf = leaf.exceptions[0]
        raise leaf from None
    finally:
        for lines in logs:
            for line in lines:
                say(line)
    if gate.refusal is not None:
        raise gate.refusal


async def _review_until_done(
    gate: _Gate,
    inst: Installation,
    tasks: Path,
    units: Sequence[StoredUnit],
    reviews: Mapping[str, Review],
    mechanical: Callable[[Path], list[str]],
    say: Callable[[str], None],
) -> None:
    """Review one change, and again after each repair that was committed."""
    change = tasks.parent.name
    earlier = reviews.get(change)
    while True:
        earlier = await _review_change(gate, inst, change, tasks, units, earlier, mechanical, say)
        if earlier is None:
            return


async def _review_change(
    gate: _Gate,
    inst: Installation,
    change: str,
    tasks: Path,
    units: Sequence[StoredUnit],
    earlier: Review | None,
    mechanical: Callable[[Path], list[str]],
    say: Callable[[str], None],
) -> Review | None:
    """Review `change` once if its plan has no review; return the review when a repair was
    committed, so it is reviewed again, or None when nothing more is to be done this round."""
    path = record_path(inst)
    mine = build_order(units, change)
    digest = plan_hash(tasks.parent, [unit for unit in units if unit.change == change])
    now = spans.clock.now()
    same = earlier is not None and earlier.hash == digest
    if earlier is not None and same and not (earlier.failed and earlier.retry_due(now)):
        return None
    attempts = earlier.attempts + 1 if earlier is not None and same else 1
    kept = earlier.kept if earlier is not None else ()
    repairs = earlier.repairs if earlier is not None else 0
    try:
        report = mechanical(tasks)
    except Exception as error:  # the report is context, never a reason to skip the review
        say(f"plan review {change}: the mechanical report could not be read: {error}")
        report = []
    outcome = await _review_once(gate, inst, change, tasks, mine, report, say)
    if outcome is None:
        return None  # a call was stopped: nothing is recorded, so the plan is asked again
    if isinstance(outcome, PlannerError):
        error = outcome
        say(f"plan review {change}: {error}")
        _record(
            path,
            change,
            Review(
                hash=digest,
                error=str(error),
                attempts=attempts,
                failed_at=now,
                permanent=isinstance(error.__cause__, PromptTooLarge),
                kept=kept,
                repairs=repairs,
            ),
        )
        return None
    findings = _not_kept(outcome, kept, group_texts(tasks))
    review = Review(hash=digest, findings=findings, kept=kept, repairs=repairs)
    fixable = [found for found in review.blockers if found.fix.strip()]
    if fixable and repairs < inst.config.planning.plan_review_repairs:
        async with gate.repairs:  # one repair at a time: each commits to the planning repo
            try:
                why = await gate.call(lambda: repair(inst, change, tasks, fixable, say=say))
            except _Stopped:
                return None  # not recorded, so the plan is reviewed and repaired next time
        review = review.model_copy(update={"repairs": repairs + 1})
        _record(path, change, review)
        if not why:
            say(f"plan review {change}: repaired {len(fixable)} finding(s); reviewing again")
            return review
        say(f"plan review {change}: not repaired: {why}")
    else:
        _record(path, change, review)
    if review.blockers:
        say(
            f"plan review {change}: held, {len(review.blockers)} blocker(s)"
            + (
                f" and {len(review.findings) - len(review.blockers)} advice"
                if len(review.findings) > len(review.blockers)
                else ""
            )
            + f"; see `abk review-plan show {change}`"
        )
    elif review.findings:
        say(f"plan review {change}: {len(review.findings)} advice, not held")
    return None
