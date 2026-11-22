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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from agent_build_kit import runtimes
from agent_build_kit.config import models
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.call_record import recorded
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import BUILDS_NOTHING, FINISHED_STATES
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import PromptTooLarge, check_prompt_size

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

Artifacts:
{artifacts}

Answer with a short reading, then one JSON object on its own, `{{"findings": [...]}}`. Each
finding is `{{"group": <group number>, "question": <question number>, "evidence": "<what you
found, naming the files>"}}`. Report only what you can show; `{{"findings": []}}` when the plan
can work.
"""


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

    @property
    def holds(self) -> bool:
        return bool(self.findings) and not self.cleared


class Unreadable(ValueError):
    """The model's answer held no findings that could be read."""


def record_path(inst: Installation) -> Path:
    return inst.state_dir / RECORD


def read_reviews(path: Path) -> dict[str, Review]:
    """Every change's recorded review; none when the file is missing or unreadable."""
    try:
        raw = json.loads(path.read_text())
        return {change: Review.model_validate(entry) for change, entry in raw.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _write(path: Path, reviews: Mapping[str, Review]) -> None:
    body = {change: review.model_dump(mode="json") for change, review in reviews.items()}
    atomic_write_text(path, json.dumps(body, indent=2, sort_keys=True) + "\n")


def _record(path: Path, change: str, review: Review) -> None:
    with file_lock(path.with_name(f"{path.name}.lock")):
        reviews = read_reviews(path)
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


def _artifacts(folder: Path) -> str:
    paths = [folder / name for name in ARTIFACTS]
    paths += sorted((folder / "specs").glob("**/spec.md"))
    paths.append(folder / "tasks.md")
    return "\n\n".join(
        f"### {path.relative_to(folder)}\n{path.read_text()}" for path in paths if path.is_file()
    )


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
    """A hash of what a review reads: the change's artifacts and its planned units."""
    text = _artifacts(folder) + "\n" + "\n".join(sorted(_unit_line(unit) for unit in units))
    return hashlib.sha256(text.encode()).hexdigest()


def build_prompt(
    change: str, folder: Path, units: Sequence[StoredUnit], report: Sequence[str]
) -> str:
    """The request: the questions, the artifacts, the units and the mechanical checks' report."""
    return PROMPT.format(
        change=change,
        questions="\n".join(f"{number}. {text}" for number, text in enumerate(QUESTIONS, 1)),
        report="\n".join(report) or "(nothing)",
        units="\n".join(_unit_line(unit) for unit in units),
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
        digest = plan_hash(tasks.parent, mine)
        if (earlier := reviews.get(change)) is not None and earlier.hash == digest:
            continue
        try:
            report = mechanical(tasks)
        except Exception as error:  # the report is context, never a reason to skip the review
            say(f"plan review {change}: the mechanical report could not be read: {error}")
            report = []
        prompt = build_prompt(change, tasks.parent, mine, report)
        agent = runtimes.active()
        request = recorded(
            AgentRequest(
                prompt=prompt,
                permission_mode="allowed_tools_only",
                change=change,
                role="plan",
                model=models().plan or None,
            ),
            agent,
            node=OverheadNode.PLAN,
            change=change,
            say=say,
        )
        try:
            check_prompt_size(request, agent.prompt_transport)
        except PromptTooLarge as error:
            say(f"plan review {change}: not asked, {error}")
            continue
        result = agent.run(request)
        if not result.ok:
            say(f"plan review {change}: the review failed: {result.error}")
            continue
        try:
            findings = parse_findings(result.text)
        except Unreadable as error:
            say(f"plan review {change}: the answer could not be read: {error}")
            continue
        _record(path, change, Review(hash=digest, findings=findings))
        if findings:
            say(
                f"plan review {change}: held, {len(findings)} finding(s); "
                f"see `abk review-plan show {change}`"
            )
