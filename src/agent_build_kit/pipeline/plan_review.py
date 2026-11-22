"""A model reads a change's plan before its first unit starts; a finding holds the change.

The four questions the model is asked are `QUESTIONS`, in order: a finding names its question
by the number (from 1) of the one it answers. A review is recorded with a hash of what it read
(the change's artifacts and its planned units), and a change whose hash has a review is not
reviewed again. A change with findings is held until a person clears them (`abk review-plan
clear`) or edits `tasks.md`, which gives a new hash and a new review. A review that fails holds
nothing and is logged, so the review can never stop the pipeline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import shell, spans
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.planner import PlannerError, ask_plan_model
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import BUILDS_NOTHING, FINISHED_STATES
from agent_build_kit.pipeline.work_graph import specification_text, validate_tasks
from agent_build_kit.runtimes.base import PromptTooLarge

logger = logging.getLogger(__name__)

# The fixed questions every review asks, in the order a finding numbers them.
QUESTIONS: tuple[str, ...] = (
    "Does each unit end with the suite green, given what its groups move, rename or delete?",
    "Does any task need live numbers, an installation edit or an edit to the change's own files?",
    "Can each `Check:` run in the check environment?",
    "Does a later group's test assert something an earlier unit already broke?",
)

RECORD = "plan_reviews.json"
ARTIFACTS = ("proposal.md", "design.md")

PROMPT = """You are reviewing the plan of the change `{change}` before its first unit is built.
Read the change's artifacts and its planned units below, and answer the numbered questions.

Questions:
{questions}

The mechanical checks already report the following for this change. Do not repeat it:
{report}

Planned units:
{units}

Files the tasks name, as they stand on each repo's default branch:
{repository}

Artifacts:
{artifacts}

Answer with a short reading, then one JSON object on its own, `{{"findings": [...]}}`. Each
finding is `{{"group": <group number>, "question": <question number>, "evidence": "<what you
found, naming the files>"}}`. Report only what you can show; `{{"findings": []}}` when the plan
can work.
"""

# A failed review is asked again after this long, at most `MAX_ATTEMPTS` times for one plan; a
# prompt that was too large is not asked again until the plan changes.
RETRY_AFTER = timedelta(hours=1)
MAX_ATTEMPTS = 3
# The most bytes of the repository's files the request carries, and of any one file.
VIEW_BUDGET = 60_000
VIEW_FILE_LIMIT = 12_000


class Finding(Frozen):
    """One thing a review found: the group, the question (from 1) and the evidence."""

    group: int
    question: int
    evidence: str


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

    @property
    def holds(self) -> bool:
        return bool(self.findings) and not self.cleared

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
    """The changes whose review has findings no person has cleared, each with its review."""
    return {
        change: review for change, review in read_reviews(record_path(inst)).items() if review.holds
    }


def clear(inst: Installation, change: str, note: str = "") -> int:
    """Clear the findings standing on `change`, keeping them and `note` with the review; return
    how many were cleared (none when no finding stood)."""
    path = record_path(inst)
    with file_lock(path.with_name(f"{path.name}.lock")):
        reviews = read_reviews(path)
        review = reviews.get(change)
        if review is None or not review.holds:
            return 0
        reviews[change] = review.model_copy(update={"cleared": True, "note": note})
        _write(path, reviews)
        return len(review.findings)


def finding_lines(review: Review) -> list[str]:
    """One line per finding, as `show` and `abk status` print them."""
    return [
        f"group {found.group}, question {found.question}: {found.evidence}"
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
    """The backticked path-like names in a group's lines, in order, once each."""
    found = (name for line in body for name in re.findall(r"`([^`\s]+)`", line))
    pathlike = (name for name in found if "/" in name and not re.search(r"[*$<>{}]", name))
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


def _unit_line(unit: StoredUnit) -> str:
    groups = ", ".join(
        f"{member.change} group {number}" for member in unit.members() for number in member.groups
    )
    return f"- {unit.id} [{unit.repo}, {unit.tier}] ({groups}): {unit.title}"


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
) -> str:
    """The request: the questions, the artifacts, the units and the mechanical checks' report."""
    return PROMPT.format(
        change=change,
        questions="\n".join(f"{number}. {text}" for number, text in enumerate(QUESTIONS, 1)),
        report="\n".join(report) or "(nothing)",
        units="\n".join(_unit_line(unit) for unit in units),
        repository=repository or "(none)",
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


def review_changes(
    inst: Installation,
    units: Sequence[StoredUnit],
    *,
    mechanical: Callable[[Path], list[str]],
    say: Callable[[str], None],
) -> None:
    """Review each change with open units whose plan has no review yet, and record what the
    model finds. A review that fails is logged and holds nothing."""
    if not inst.config.planning.review_plans:
        return
    path = record_path(inst)
    reviews = read_reviews(path)
    for tasks in sorted(inst.tasks_files()):
        change = tasks.parent.name
        mine = open_units(units, change)
        if not mine:
            continue
        digest = plan_hash(tasks.parent, [unit for unit in units if unit.change == change])
        now = spans.clock.now()
        earlier = reviews.get(change)
        same = earlier is not None and earlier.hash == digest
        if earlier is not None and same and not (earlier.failed and earlier.retry_due(now)):
            continue
        attempts = earlier.attempts + 1 if earlier is not None and same else 1
        try:
            report = mechanical(tasks)
        except Exception as error:  # the report is context, never a reason to skip the review
            say(f"plan review {change}: the mechanical report could not be read: {error}")
            report = []
        prompt = build_prompt(change, tasks.parent, mine, report, repository_view(inst, tasks))
        try:
            answer = ask_plan_model(prompt, change=change, say=say)
            try:
                findings = parse_findings(answer)
            except Unreadable as error:
                raise PlannerError(f"the answer could not be read: {error}") from error
        except PlannerError as error:
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
                ),
            )
            continue
        _record(path, change, Review(hash=digest, findings=findings))
        if findings:
            say(
                f"plan review {change}: held, {len(findings)} finding(s); "
                f"see `abk review-plan show {change}`"
            )
