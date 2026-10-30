"""Task-group tags: parsing and validation.

An OpenSpec change's `tasks.md` is the input the runner turns into units of
work. Two facts have to be on every task group for that to be possible: the
repo the group's code lands in, and the test tier it needs. They are written
as a tagged heading:

    ## 2. [app] [e2e-test] Relay the archived event to the new consumer

`openspec/config.yaml`'s `rules:` tell the authoring model to write them that
way, but rules are a prompt input, not a check — OpenSpec's own
`validate --strict` has no opinion about them. This module is the check.

It runs in CI on the change's own PR (see .github/workflows/ci.yml), so a
missing or misspelled tag is caught while the change is being reviewed. Without
it, the first sign of trouble is the runner failing to route a unit, days
later, after the change has merged and work has already started.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from agent_build_kit.compat_names import (
    Place,
    TestKind,
    is_old_spelling,
    new_spelling,
    notice,
)
from agent_build_kit.config import (
    REST_SPLIT,
    SPLIT_NAME,
    ProjectConfig,
    RepoConfig,
    WorkspaceConfig,
    active,
    e2e_splits,
    owning_project,
)
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.pipeline.group_paths import allows_no_code, named_paths
from agent_build_kit.pipeline.units import ManualStep, Priority, project_tag, reachable


class HasPath(Protocol):
    """A project, declared or detected: all a heading needs of it is its `path`."""

    @property
    def path(self) -> str: ...


def known_repos() -> tuple[str, ...]:
    """The repos a unit can land in: the active workspace's, as a closed set.

    Closed rather than anything that looks like a name: a near-miss (a
    capital, an underscore for a hyphen) would otherwise reach the runner and
    fail there instead of here. Empty when no workspace is loaded, which turns
    the check off rather than failing every heading.
    """
    return tuple(active().repos)


def project_tags(projects: Iterable[HasPath]) -> tuple[str, ...]:
    """The projects of a repo (declared or detected) beside its root, as a heading writes them."""
    return tuple(path for p in projects if (path := tag_path(p.path)) != ".")


def declared_projects(repos: Mapping[str, RepoConfig]) -> dict[str, tuple[str, ...]]:
    """The projects each repo declares beside its root, by the `path` a heading writes."""
    return {name: project_tags(repo.projects) for name, repo in repos.items()}


def tag_path(path: str) -> str:
    """A declared project path as a heading writes it: no leading `./`, no trailing `/`."""
    return path.removeprefix("./").rstrip("/") or "."


def repo_tag(repo: str, project_path: str) -> str:
    """The first tag of a group heading for `project_path` of `repo`: `[app]` for the root
    project, `[app/web]` for another."""
    path = tag_path(project_path)
    return f"[{repo}]" if path == "." else f"[{repo}/{path}]"


# The tags a group heading is read with: the new spellings and, with a notice, the old ones.
# A unit-test runs on the code host's checks; an e2e-test needs the live local stack on this host
# and is serialized behind one lock (docs/architecture.md).
TEST_KIND_TAGS = tuple(member.value for member in TestTier)

# An optional third tag, for the one case a group cannot be checked without it.
#
# `contract` marks a group that changes a shape the OTHER repo consumes — a
# field in a shared wire model, an event one repo produces and the other
# reads, a tool surface. A consumer pins its platform at a SHA, so the two are
# never at the same commit and callers of both shapes exist for an unbounded
# window: the widening has to land alone, and something has to remove the old
# half later.
# `narrow` is that something, and it must be the last group.
#
# Deliberately NOT for contracts inside one repo. There a change and its
# callers land in the same commit, so no window exists and nothing needs
# flagging.
#
# `acceptance` marks the group that drives the change's surface the way its
# consumer does, on the stack, after everything else it exercises: every
# change has one, or says why not (ACCEPTANCE_OPT_OUT). A change can pass
# every unit's review and tier with bugs a scripted run of its surface as a
# real client finds in minutes (docs/architecture.md).
FLAGS = ("contract", "narrow", "acceptance")

# What the name of every new change that fixes a failing test starts with, whatever its kind.
# Its group carries `contract` for the full review that flag floors, not for a shape it widens,
# so it needs no `narrow` group after it.
FIX_PREFIX = "fix-test"

# "Acceptance: none — a refactor, nothing a consumer sees changes": a change
# with no surface to exercise, and the reason, which is what gets reviewed.
ACCEPTANCE_OPT_OUT = re.compile(r"^Acceptance:\s*none\b\s*[—–-]*\s*(?P<reason>.*?)\s*$", re.I)

# "## 2. [app] [e2e-test] Relay the archived event" — the tags are required, so a
# heading missing them doesn't match and is reported rather than skipped.
GROUP_HEADING = re.compile(
    r"^##\s+(?P<number>\d+)\.\s+\[(?P<repo>[^\]]*)\]\s+\[(?P<tier>[^\]]*)\]"
    r"(?:\s+\[(?P<flag>[^\]]*)\])?\s+(?P<title>.+?)\s*$"
)
ANY_GROUP_HEADING = re.compile(r"^##\s+(?P<rest>.+?)\s*$")
GROUP_NUMBER = re.compile(r"^##\s+(?P<number>\d+)\.")


def group_sections(tasks: str, groups: Iterable[int]) -> list[str]:
    """The raw sections of a `tasks.md` text for the groups numbered in `groups`, each from its
    heading to the next numbered heading."""
    wanted = set(groups)
    sections: list[str] = []
    keeping = False
    for line in tasks.splitlines(keepends=True):
        if found := GROUP_NUMBER.match(line):
            keeping = int(found.group("number")) in wanted
            if keeping:
                sections.append("")
        if keeping:
            sections[-1] += line
    return sections


# "Needs: feature group 2 — why", inside a group: that group cannot pass until
# a group of *another* change has. The planner orders groups within a change;
# across changes it only sees what is already in flight, and its answer is a
# model's, so a dependency that must hold is written down and applied as code.
# A single word `merged` straight after the group number makes the line wait for the
# parent's merge; it is recognised so it is not read into the reason. Anywhere else the
# word is part of the reason.
NEEDS_LINE = re.compile(
    r"^Needs:\s*(?P<change>[a-z0-9][a-z0-9-]*)\s+group\s+(?P<group>\d+)\b"
    r"(?:\s+(?P<merged>merged)(?=\s|$))?\s*[—–-]*\s*(?P<reason>.*?)\s*$",
    re.I,
)

_CHECKBOX = re.compile(r"^(\s*-\s*\[)[ xX](\])", re.MULTILINE)


def retag_headings(text: str, spell: Callable[[str], str]) -> tuple[str, int]:
    """`text` with the test-kind tag of each group heading spelled by `spell`, and how many
    changed; every other byte, line endings included, comes back as it was."""
    out: list[str] = []
    count = 0
    for line in text.splitlines(keepends=True):
        found = GROUP_HEADING.match(line.splitlines()[0])
        if found and (tag := spell(found["tier"])) != found["tier"]:
            start, end = found.span("tier")
            line = line[:start] + tag + line[end:]
            count += 1
        out.append(line)
    return "".join(out), count


def current_tag(tag: str) -> str:
    """A test-kind tag in its current spelling."""
    return new_spelling(Place.TAG, tag)


def resolved_projects(groups: Iterable[TaskGroup]) -> dict[int, str]:
    """The project of each group that was resolved from its paths, by group number."""
    return {g.number: g.project for g in groups if g.source == ProjectSource.RESOLVED}


def specification_text(
    text: str,
    spell: Callable[[str], str] = current_tag,
    resolved: Mapping[int, str] | None = None,
) -> str:
    """A tasks file's text with progress stripped out, and the test-kind tags spelled by `spell`
    (their current spelling unless a plan recorded before the rename is being matched). The
    projects `resolved` (see `resolved_projects`) follow it, so a plan is stale when the
    declared projects move a group's resolution.

    What a re-plan should key on is what the change *asks for*, not how much
    of it is done. The pipeline ticks these boxes as units land, and hashing
    the raw file would re-plan on every tick — with the planner then seeing
    the work marked done and proposing a graph that built no groups at all.
    """
    # `Needs:` lines too: they only add dependencies, which `link_needs`
    # applies on its own. Re-planning a change for one would be a model call
    # that can reshuffle units already built. Blank lines go with them: a
    # `Needs:` line comes with the blank line that sets it off.
    spelled, _ = retag_headings(text, spell)
    stripped = _CHECKBOX.sub(r"\1 \2", spelled)
    kept = [
        line
        for line in stripped.splitlines()
        if line.strip() and not NEEDS_LINE.match(line.strip())
    ]
    return "\n".join([*kept, *(f"resolved: group {n} in {p}" for n, p in (resolved or {}).items())])


# "Separate: reviewed and reverted on its own", inside a group: no other change's
# groups are joined to its unit and it is never joined to another. The reason is
# what review agrees to, as with `Acceptance: none`.
SEPARATE_LINE = re.compile(r"^Separate:\s*(?P<reason>.*?)\s*$", re.I)

# "Tests: required — the setting keeps the disk bounded", inside a group: it is built tests first
# even when it touches no code. The reason is what review agrees to.
TESTS_LINE = re.compile(r"^Tests:\s*(?P<rest>.*?)\s*$", re.I)
TESTS_REQUIRED = re.compile(r"^required\s*[—–-]+\s*(?P<reason>\S.*)$", re.I)

# "Independent: only adds a receiver", inside a group: it depends on no earlier
# group of its change. The reason is what review agrees to.
INDEPENDENT_LINE = re.compile(r"^Independent:\s*(?P<reason>.*?)\s*$", re.I)

# "Support: `scripts/seed.sh`, `compose.e2e.yml` — <reason>", inside an e2e-test group: the
# files it may hold beside tests, docs and the changelog; a trailing `/` covers a directory.
SUPPORT_LINE = re.compile(
    r"^Support:\s*(?P<paths>(?:`[^`]+`[\s,]*)+)(?:[—–-]+\s*(?P<reason>.*?))?\s*$", re.I
)

# "Paths: `web/src/**`, `web/tests/x.py`", inside a group: the paths it changes, which decide its
# project when the heading names none. "Reads: `docs/x.md`": paths it only reads, which do not.
PATHS_LINE = re.compile(r"^Paths:\s*(?P<paths>(?:`[^`]+`[\s,]*)+)$", re.I)
READS_LINE = re.compile(r"^Reads:\s*(?P<paths>(?:`[^`]+`[\s,]*)+)$", re.I)

# `[app/<root>]` in a heading keeps the group in the root project, whatever paths it names.
ROOT_SPELLING = "<root>"

# "Manual: <slug> — <what a person does> — runbook: <path>#<heading>", inside a group: a step
# only a person can do, with the runbook entry that says how. A `Check: <command>` line after
# it is the deterministic check the tick runs to see the step is done.
MANUAL_LINE = re.compile(
    r"^Manual:\s*(?P<slug>[a-z0-9][a-z0-9-]*)\s+[—–]\s*(?P<text>.*?)\s*[—–]\s*"
    r"runbook:\s*(?P<runbook>\S+)\s*$",
    re.I,
)
CHECK_LINE = re.compile(r"^Check:\s*(?P<command>.*?)\s*$", re.I)

# "Priority: 2", inside a group: how urgent its unit is, 0 (emergency) to 5, 3 when
# unsaid. Above the first group it is the default for the change's groups.
PRIORITY_LINE = re.compile(r"^Priority:\s*(?P<value>.*?)\s*$", re.I)
PRIORITY_VALUE = re.compile(r"[0-5]")

# `Split: <name>` in an e2e-test group: the e2e-test split it runs in (`rest` when absent).
SPLIT_LINE = re.compile(r"^Split:\s*(?P<value>.*?)\s*$", re.I)

# "- [ ] 1.1 Do the thing" / "- [x] 1.1 Done". Checked and unchecked both count:
# this asks whether a group has tasks at all, not how far along it is.
TASK_LINE = re.compile(
    r"^\s*-\s+\[(?P<box>[ xX])\]\s+(?P<group>\d+)\.(?P<number>\d+)\s+(?P<text>\S.*?)\s*$"
)


class Task(Frozen):
    """One checkbox task of a change's `tasks.md`, with the key that names it."""

    # `<change>:<group>.<task>`, e.g. `feature:3.2`.
    key: str
    group: int
    number: int
    # The task's text after its number, continuation lines included, joined by newlines.
    text: str
    done: bool
    # The 1-based line of the task in the file.
    line: int


def read_tasks(tasks: Path, change: str) -> list[Task]:
    """Every checkbox task of `tasks`, in file order, keyed under `change`.

    A task's text runs over the indented lines under it and ends at a blank line, a heading or
    the next task. The tasks are the lines `TASK_LINE` accepts, and like the group parser it puts
    each one in the group whose heading it sits under, whatever number its own prefix carries,
    and leaves out a task above the first heading or under a heading that is not a readable
    group, so the per-group counts agree with the group parser's."""
    found: list[Task] = []
    open_task = False
    group: int | None = None
    for index, line in enumerate(tasks.read_text().splitlines(), start=1):
        if ANY_GROUP_HEADING.match(line):
            heading = GROUP_HEADING.match(line)
            group = int(heading["number"]) if heading else None
            open_task = False
        elif (parsed := TASK_LINE.match(line)) and group is not None:
            number = int(parsed["number"])
            found.append(
                Task(
                    key=f"{change}:{group}.{number}",
                    group=group,
                    number=number,
                    text=parsed["text"],
                    done=parsed["box"] != " ",
                    line=index,
                )
            )
            open_task = True
        elif open_task and line[:1].isspace() and line.strip():
            found[-1] = found[-1].model_copy(update={"text": f"{found[-1].text}\n{line.strip()}"})
        else:
            open_task = False
    return found


class ProjectSource(StrEnum):
    """How a group's project was decided: written in the heading, resolved from the paths the
    group names, or the root because nothing placed it elsewhere."""

    EXPLICIT = "explicit"
    RESOLVED = "resolved"
    ROOT = "root"


class GroupMode(StrEnum):
    """How a group is built: tests first then code, tests only, or no code at all."""

    TESTS_AND_CODE = "tests_and_code"
    TESTS_ONLY = "tests_only"
    NO_CODE = "no_code"


class TaskGroup(Frozen):
    """One `## N. [repo] [tier] Title` group and the tasks under it."""

    number: int
    repo: str
    tier: TestKind
    title: str
    line: int
    task_count: int
    # The project of the repo the group's work belongs to, `.` for the root project.
    project: str = "."
    # How `project` was decided.
    source: ProjectSource = ProjectSource.ROOT
    # The entries of the group's `Paths:` lines and of its `Reads:` lines.
    paths: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    # The lines under the heading, as written.
    body: tuple[str, ...] = ()
    # "contract", "narrow", "acceptance", or "" — see FLAGS.
    flag: str = ""
    # A `Separate: <reason>` line in the group: never carried by another
    # change's unit, and no other change's groups are added to its unit.
    separate: bool = False
    # An `Independent: <reason>` line in the group: it depends on no earlier
    # group of its change.
    independent: bool = False
    # 0 (emergency) to 5, from a `Priority:` line in the group or above the first.
    priority: int = Priority.NORMAL
    # A `Tests: required — <reason>` line in the group.
    tests_required: bool = False
    # Whether the paths the group names are all documents or configuration, so it may be no_code.
    code_free: bool = False
    # The "Done when" sentence under the heading, "" when the group has none.
    goal: str = ""
    # The e2e-test split of an e2e-test group, from its `Split:` line; `rest` when it has none.
    split: str = REST_SPLIT
    # The `Manual:` lines of the group, each with its optional `Check:` line.
    manual_steps: tuple[ManualStep, ...] = ()
    # The paths of the `Support:` lines of an e2e-test group: files it may hold beside tests, docs
    # and the changelog. A trailing `/` covers a directory.
    support: tuple[str, ...] = ()

    @property
    def tag(self) -> str:
        """The first tag of the heading: the repo, and `/project` unless it is the root project."""
        return project_tag(self.repo, self.project)

    @property
    def mode(self) -> GroupMode:
        """The group's floor build mode, from its tier, the paths it names and its `Tests:` line."""
        if self.tier == TestTier.E2E_TEST:
            return GroupMode.TESTS_ONLY
        if self.code_free and not self.tests_required:
            return GroupMode.NO_CODE
        return GroupMode.TESTS_AND_CODE

    @property
    def test_only(self) -> bool:
        """Whether the group builds no implementation: its mode is `tests_only`."""
        return self.mode is GroupMode.TESTS_ONLY


def resolved_project(group: TaskGroup, projects: Sequence[str]) -> tuple[str, ProjectSource]:
    """The project of `group` and how it was decided, given the projects its repo declares beside
    the root (`projects`, as a heading writes them). A project written in the heading is kept; any
    other group takes the one declared project that holds every path it names, else the root."""
    if group.source == ProjectSource.EXPLICIT:
        return group.project, ProjectSource.EXPLICIT
    declared = [ProjectConfig(path=p) for p in projects]
    owners = {
        # The trailing `/` makes the project folder itself (`web`) count as inside `web/`.
        owner.path if (owner := owning_project(declared, f"{path.rstrip('/')}/")) else None
        for path in named_paths(group, projects)
    }
    if len(owners) == 1 and (owner_path := owners.pop()) is not None:
        return tag_path(owner_path), ProjectSource.RESOLVED
    return ".", ProjectSource.ROOT


def project_source_note(group: TaskGroup) -> str:
    """What a display adds after a group's tag when the project was not simply written in the
    heading: ` (resolved)`, or ` (explicit root)` for `[repo/<root>]`; nothing otherwise."""
    if group.source == ProjectSource.RESOLVED:
        return " (resolved)"
    if group.source == ProjectSource.EXPLICIT and group.project == ".":
        return " (explicit root)"
    return ""


def _resolved(group: TaskGroup, projects: Sequence[str]) -> TaskGroup:
    project, source = resolved_project(group, projects)
    code_free = allows_no_code(named_paths(group, projects))
    return group.model_copy(update={"project": project, "source": source, "code_free": code_free})


def _listed(body: Iterable[str], pattern: re.Pattern[str]) -> tuple[str, ...]:
    """The backticked entries of the lines of `body` that match `pattern`."""
    return tuple(
        entry
        for line in body
        if (found := pattern.match(line.strip()))
        for entry in re.findall(r"`([^`]+)`", found["paths"])
    )


class ValidationError(Frozen):
    """Something a human has to fix in tasks.md, with where to find it."""

    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def split_repo_tag(tag: str, repos: tuple[str, ...]) -> tuple[str, str | None]:
    """The repo and project a heading's first tag names: a tag that is a declared repo is that
    repo whole, otherwise the longest declared repo before a `/` takes the rest as its
    project. A tag naming no repo comes back whole when no repos are known, else as its first
    segment, for the unknown-repo message."""
    if tag in repos or not repos:
        return tag, None
    for name in sorted(repos, key=len, reverse=True):
        if tag.startswith(f"{name}/"):
            return name, tag[len(name) + 1 :]
    return tag.split("/", 1)[0], None


def _project_problem(number: int, repo: str, project: str, declared: tuple[str, ...]) -> str:
    if project == ".":
        return (
            f'group {number} tags the root project of repo "{repo}" as `{repo}/.` — the '
            f"root project is the untagged one, tagged [{repo}]"
        )
    head = f'group {number} has unknown project "{project}" for repo "{repo}" — '
    if not declared:
        return head + f"{repo} declares only its root project, tagged [{repo}]"
    return head + f"{repo} declares {', '.join(declared)} (its root project is tagged [{repo}])"


def declared_split_names(
    repos: Mapping[str, RepoConfig], config: WorkspaceConfig
) -> dict[str, tuple[str, ...]]:
    """The e2e-test splits each repo declares under `config`, `rest` last, as `Split:` may
    name them."""
    return {
        name: tuple(split.name for split in e2e_splits(repo, config))
        for name, repo in repos.items()
    }


def _split_problem(number: int, repo: str, tier: str, value: str, declared: tuple[str, ...]) -> str:
    """Why `Split: <value>` is refused in group `number`, or "" when it is accepted."""
    if tier != TestTier.E2E_TEST:
        return f"group {number} is a {tier} group, and a {tier} group has no e2e-test run to split"
    if "," in value or len(value.split()) > 1:
        return (
            f'group {number} names more than one split ("{value}") — a group is in one split, '
            "and a test which must run in two splits is written as two groups, one for each"
        )
    if not SPLIT_NAME.fullmatch(value):
        return (
            f'group {number} has the split name "{value}" — a split name is lowercase '
            "letters, digits and underscores"
        )
    if value == REST_SPLIT or value in declared:
        return ""
    if declared == (REST_SPLIT,) or not declared:
        return (
            f'group {number} is in split "{value}" but repo "{repo}" declares no e2e-test '
            f"splits, so only `{REST_SPLIT}` (or no `Split:` line) is accepted"
        )
    named = ", ".join(f"`{name}`" for name in declared[:-1])
    return (
        f'group {number} is in split "{value}" but repo "{repo}" declares {named} and '
        f"`{declared[-1]}`"
    )


def validate_tasks_text(
    text: str,
    change: str,
    *,
    repos: tuple[str, ...] | None = None,
    projects: Mapping[str, tuple[str, ...]] | None = None,
    splits: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[list[TaskGroup], list[ValidationError]]:
    """`validate_tasks` of `text` as the tasks of the change `change`, which it is written to
    under a scratch directory of that name, where the parse reads the name of its own change."""
    with tempfile.TemporaryDirectory() as scratch:
        probe = Path(scratch) / change / "tasks.md"
        probe.parent.mkdir()
        probe.write_bytes(text.encode())
        return validate_tasks(probe, repos=repos, projects=projects, splits=splits)


def validate_tasks(
    path: Path,
    *,
    repos: tuple[str, ...] | None = None,
    projects: Mapping[str, tuple[str, ...]] | None = None,
    splits: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[list[TaskGroup], list[ValidationError]]:
    """Parse a change's tasks.md and report everything wrong with its groups.

    Returns the groups it could parse and every error found. All errors are
    collected rather than raising on the first, so one CI run shows the whole
    list instead of one problem per push.
    """
    repos = known_repos() if repos is None else repos
    projects = declared_projects(active().repos) if projects is None else projects
    splits = declared_split_names(active().repos, active()) if splits is None else splits
    lines = path.read_text().splitlines()

    groups: list[TaskGroup] = []
    errors: list[ValidationError] = []
    tasks_seen: list[int] = []
    heading_lines: list[int] = []
    separate: set[int] = set()
    tests_required: set[int] = set()
    independent: dict[int, int] = {}
    manual: dict[int, list[ManualStep]] = {}
    manual_slugs: set[str] = set()
    support: dict[int, list[str]] = {}
    current: int | None = None
    default_priority: int | None = None
    priorities: dict[int, int] = {}
    stray_priority: dict[int, int] = {}
    # The group the lines being read belong to, when its heading was read: (number, repo, tier).
    reading: tuple[int, str, str] | None = None
    split_lines: dict[int, int] = {}
    split_of: dict[int, str] = {}
    split_refused: set[int] = set()
    root_lines: set[int] = set()

    own_merged_lines = {need.line for _, need in merged_needs(path) if names_own_change(need, path)}
    for index, text in enumerate(lines, start=1):
        if TASK_LINE.match(text):
            if tasks_seen:
                tasks_seen[-1] += 1
            continue

        heading = ANY_GROUP_HEADING.match(text)
        if heading is None:
            if found := PRIORITY_LINE.match(text.strip()):
                if not PRIORITY_VALUE.fullmatch(found["value"]):
                    errors.append(
                        ValidationError(
                            line=index,
                            message=f'`Priority:` is "{found["value"]}", expected an integer '
                            "from 0 (emergency) to 5",
                        )
                    )
                elif (default_priority if current is None else priorities.get(current)) is None:
                    if current is None:
                        default_priority = int(found["value"])
                    else:
                        priorities[current] = int(found["value"])
                        stray_priority[current] = index
                else:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="a second `Priority:` line in the same place — "
                            "one sets the whole group, or the change above its groups",
                        )
                    )
            if found := SPLIT_LINE.match(text.strip()):
                if current is None:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Split:` above the first group belongs to no group — "
                            "write it inside the group it is for",
                        )
                    )
                elif reading is None:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Split:` is in a group whose heading could not be read, "
                            "so it sets nothing",
                        )
                    )
                elif current in split_lines:
                    split_refused.add(current)
                    errors.append(
                        ValidationError(
                            line=index,
                            message="a second `Split:` line — a group is in one split, and a "
                            "test which must run in two splits is written as two groups, one "
                            "for each",
                        )
                    )
                else:
                    split_lines[current] = index
                    group_number, repo_name, tier_name = reading
                    problem = _split_problem(
                        group_number,
                        repo_name,
                        tier_name,
                        found["value"],
                        splits.get(repo_name, ()),
                    )
                    if problem:
                        split_refused.add(current)
                        errors.append(ValidationError(line=index, message=problem))
                    else:
                        split_of[current] = found["value"]
            if current is not None and index in own_merged_lines:
                errors.append(
                    ValidationError(
                        line=index,
                        message="`merged` on a Needs: for this change's own group says "
                        "nothing — the groups of one change are ordered already",
                    )
                )
            if current is not None and (kept := SEPARATE_LINE.match(text.strip())):
                if kept["reason"]:
                    separate.add(current)
                else:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Separate:` needs a reason after it — the reason is "
                            "what review agrees to",
                        )
                    )
            if current is not None and (said := TESTS_LINE.match(text.strip())):
                if TESTS_REQUIRED.match(said["rest"]):
                    tests_required.add(current)
                else:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Tests:` takes `required — <reason>`; the reason is "
                            "what review agrees to",
                        )
                    )
            if current is not None and text.strip().lower().startswith("support:"):
                found = SUPPORT_LINE.match(text.strip())
                if reading is not None and reading[2] != TestTier.E2E_TEST:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Support:` is for an [e2e-test] group, which holds tests "
                            f"only; group {reading[0]} is a {reading[2]} group",
                        )
                    )
                elif found is None or not found["reason"]:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Support:` reads `Support: `<path>`, ... — <reason>`, "
                            "with a reason after the paths — the reason is what review agrees to",
                        )
                    )
                elif reading is not None:
                    support.setdefault(current, []).extend(re.findall(r"`([^`]+)`", found["paths"]))
            if current is not None and text.strip().lower().startswith("manual:"):
                step = MANUAL_LINE.match(text.strip())
                if step is None or not step["text"]:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Manual:` reads `Manual: <slug> — <what a person does> — "
                            "runbook: <path>#<heading>`, with a description",
                        )
                    )
                elif step["slug"] in manual_slugs:
                    errors.append(
                        ValidationError(
                            line=index,
                            message=f"`Manual:` slug `{step['slug']}` is used twice in this change",
                        )
                    )
                else:
                    manual_slugs.add(step["slug"])
                    manual.setdefault(current, []).append(
                        ManualStep(
                            slug=step["slug"],
                            text=step["text"],
                            runbook=step["runbook"],
                            line=index,
                        )
                    )
            if current is not None and (check := CHECK_LINE.match(text.strip())):
                if not check["command"] or current not in manual:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Check:` needs a command, and follows a `Manual:` line "
                            "of its group",
                        )
                    )
                else:
                    last = manual[current][-1]
                    manual[current][-1] = last.model_copy(update={"check": check["command"]})
            if current is not None and (free := INDEPENDENT_LINE.match(text.strip())):
                if free["reason"]:
                    independent[current] = index
                else:
                    errors.append(
                        ValidationError(
                            line=index,
                            message="`Independent:` needs a reason after it — the reason is "
                            "what review agrees to",
                        )
                    )
            continue

        current = index
        reading = None
        heading_lines.append(index)
        tasks_seen.append(0)

        tagged = GROUP_HEADING.match(text)
        if tagged is None:
            errors.append(
                ValidationError(
                    line=index,
                    message=f'group "{heading.group("rest")}" is missing its tags — '
                    f"headings are `## <n>. [<repo>] [<kind>] <title>`, "
                    f"`[<repo>/<project>]` naming a project of the repo, "
                    f"repo one of {', '.join(repos) or '<the workspace repos>'}, "
                    f"kind one of {', '.join(TEST_KIND_TAGS)}",
                )
            )
            continue

        tier = tagged.group("tier")
        number = int(tagged.group("number"))
        repo, project = split_repo_tag(tagged.group("repo"), repos)
        if project == ROOT_SPELLING:
            project = "."
            root_lines.add(index)

        if repos and repo not in repos:
            errors.append(
                ValidationError(
                    line=index,
                    message=f'group {number} has unknown repo "{repo}" — '
                    f"expected one of {', '.join(repos)}",
                )
            )
            continue

        declared = projects.get(repo, ())
        if (
            project is not None
            and index not in root_lines
            and (project == "." or (repos and project not in declared))
        ):
            errors.append(
                ValidationError(
                    line=index, message=_project_problem(number, repo, project, declared)
                )
            )
            continue

        flag = tagged.group("flag")
        if flag is not None and flag not in FLAGS:
            errors.append(
                ValidationError(
                    line=index,
                    message=f'group {number} has unknown flag "{flag}" — '
                    f"expected one of {', '.join(FLAGS)}, or no third tag at all",
                )
            )
            continue

        if (tier := new_spelling(Place.TAG, tier)) not in TEST_KIND_TAGS:
            errors.append(
                ValidationError(
                    line=index,
                    message=f'group {number} has unknown tier "{tier}" — '
                    f"expected one of {', '.join(TEST_KIND_TAGS)}",
                )
            )
            continue

        reading = (number, repo, tier)
        groups.append(
            TaskGroup(
                number=number,
                repo=repo,
                project=project or ".",
                source=ProjectSource.ROOT if project is None else ProjectSource.EXPLICIT,
                tier=TestTier(tier),
                title=tagged.group("title"),
                line=index,
                task_count=0,
                flag=flag or "",
            )
        )

    # task_count is only known once the following lines have been read, so the
    # groups are rebuilt here rather than mutated in place.
    counts = dict(zip(heading_lines, tasks_seen, strict=True))
    ends = dict(zip(heading_lines, [*heading_lines[1:], len(lines) + 1], strict=False))
    bodies = {g.line: tuple(lines[g.line : ends[g.line] - 1]) for g in groups}
    groups = [
        TaskGroup(
            number=g.number,
            repo=g.repo,
            project=g.project,
            source=g.source,
            paths=_listed(bodies[g.line], PATHS_LINE),
            reads=_listed(bodies[g.line], READS_LINE),
            body=bodies[g.line],
            tier=g.tier,
            title=g.title,
            line=g.line,
            task_count=counts[g.line],
            flag=g.flag,
            split=REST_SPLIT if g.line in split_refused else split_of.get(g.line, REST_SPLIT),
            goal=_goal(lines, g.line),
            separate=g.line in separate,
            tests_required=g.line in tests_required,
            independent=g.line in independent,
            manual_steps=tuple(manual.get(g.line, ())),
            support=tuple(support.get(g.line, ())),
            priority=priorities.get(
                g.line, Priority.NORMAL if default_priority is None else default_priority
            ),
        )
        for g in groups
    ]
    groups = [_resolved(g, projects.get(g.repo, ())) for g in groups]

    for line in sorted(set(stray_priority) - {g.line for g in groups}):
        errors.append(
            ValidationError(
                line=stray_priority[line],
                message="`Priority:` is in a group that could not be read, so it sets nothing",
            )
        )

    for position, group in enumerate(groups):
        if group.line not in independent:
            continue
        if position == 0:
            problem = "it is the first group, with nothing to be independent of"
        elif group.flag:
            problem = f"a [{group.flag}] group is ordered after the others by what it is"
        else:
            continue
        errors.append(
            ValidationError(
                line=independent[group.line],
                message=f"group {group.number} says `Independent:` but {problem}",
            )
        )

    if not heading_lines:
        errors.append(
            ValidationError(line=1, message="no task groups found — expected `## 1. ...`")
        )
        return groups, errors

    for group in groups:
        if group.task_count == 0:
            errors.append(
                ValidationError(line=group.line, message=f"group {group.number} has no tasks")
            )

    # A widening left without its narrowing is the failure nobody notices: the
    # compatibility shim becomes the contract. Checked rather than left to
    # config.yaml's rules, because a rule is a prompt input and this one has a
    # cost that only shows up much later.
    if not path.parent.name.startswith(f"{FIX_PREFIX}-") and any(
        g.flag == "contract" for g in groups
    ):
        narrowing = [g for g in groups if g.flag == "narrow"]
        if not narrowing:
            errors.append(
                ValidationError(
                    line=groups[0].line,
                    message="a group is flagged [contract], so the change must end with a "
                    "group flagged [narrow] that removes what the widening left behind",
                )
            )
        elif narrowing[-1].number != groups[-1].number:
            errors.append(
                ValidationError(
                    line=narrowing[-1].line,
                    message="the [narrow] group must come last — work after it would "
                    "remove the old shape while something still depends on it",
                )
            )

    errors += _acceptance_errors(groups, lines)

    # Out-of-order numbering would silently change the order the runner builds
    # units in, which is the author's call, not the parser's to guess.
    expected = list(range(1, len(groups) + 1))
    if groups and [g.number for g in groups] != expected:
        errors.append(
            ValidationError(
                line=groups[0].line,
                message="task groups must be numbered from 1 in order, "
                f"found {[g.number for g in groups]}",
            )
        )

    return groups, errors


def _goal(lines: list[str], heading: int) -> str:
    """The paragraph beginning "Done when" between a group's heading and its first
    task, on one line; empty when the group has none."""
    paragraph: list[str] = []
    for text in lines[heading:]:
        if TASK_LINE.match(text) or ANY_GROUP_HEADING.match(text):
            break
        if text.strip():
            paragraph.append(text.strip())
        elif paragraph and paragraph[0].startswith("Done when"):
            break
        else:
            paragraph = []
    return " ".join(paragraph) if paragraph and paragraph[0].startswith("Done when") else ""


def _acceptance_errors(groups: list[TaskGroup], lines: list[str]) -> list[ValidationError]:
    if not groups:
        # No heading parsed: those are reported already, and there is no
        # change shape yet to hold this rule against.
        return []
    accepting = [g for g in groups if g.flag == "acceptance"]
    opt_outs = [
        (index, match["reason"])
        for index, text in enumerate(lines, start=1)
        if (match := ACCEPTANCE_OPT_OUT.match(text.strip()))
    ]
    if not accepting:
        if not opt_outs:
            return [
                ValidationError(
                    line=groups[0].line,
                    message="no group is flagged [acceptance] — end the change with a "
                    "`[e2e-test] [acceptance]` group that drives what it built the way its "
                    "consumer does, or say why there is nothing to drive with a line "
                    "`Acceptance: none — <reason>`",
                )
            ]
        index, reason = opt_outs[0]
        if not reason:
            return [
                ValidationError(
                    line=index,
                    message="`Acceptance: none` needs a reason after it — the reason is "
                    "what review agrees to",
                )
            ]
        return []

    errors = [
        ValidationError(
            line=g.line,
            message=f"group {g.number} is flagged [acceptance] but tagged [{g.tier}] — it "
            "drives the change on the stack, so it is e2e-test",
        )
        for g in accepting
        if g.tier != TestTier.E2E_TEST
    ]
    first = min(g.number for g in accepting)
    trailing = [g for g in groups if g.number > first and g.flag not in ("acceptance", "narrow")]
    errors += [
        ValidationError(
            line=g.line,
            message=f"group {g.number} comes after the [acceptance] group, which must come "
            "after every group it exercises (only a [narrow] group may follow it)",
        )
        for g in trailing
    ]
    return errors


class Need(Frozen):
    """One `Needs:` line: another change's group, and whether it must merge first."""

    change: str
    group: int
    merged: bool = False
    reason: str = ""
    line: int = 0


def group_needs(path: Path) -> dict[int, list[Need]]:
    """Each group's `Needs:` lines with their `merged` qualifier and reason."""
    needs: dict[int, list[Need]] = {}
    current: int | None = None
    for index, line in enumerate(path.read_text().splitlines(), start=1):
        if heading := GROUP_HEADING.match(line):
            current = int(heading["number"])
        elif current is not None and (found := NEEDS_LINE.match(line.strip())):
            needs.setdefault(current, []).append(
                Need(
                    change=found["change"].lower(),
                    group=int(found["group"]),
                    merged=found["merged"] is not None,
                    reason=found["reason"],
                    line=index,
                )
            )
    return needs


def names_own_change(need: Need, path: Path) -> bool:
    """Whether a `Needs:` line names a group of the change whose tasks file `path` is."""
    return need.change == path.parent.name.lower()


def merged_needs(path: Path) -> list[tuple[int, Need]]:
    """Each `Needs: ... merged` line of a tasks file with the group it sits in."""
    return [
        (group, need) for group, found in group_needs(path).items() for need in found if need.merged
    ]


def cross_repo_needs_notes(
    path: Path,
    changes_dir: Path,
    *,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
) -> list[str]:
    """One info note per plain `Needs:` line of a tasks file naming a group of another
    repository, which waits for the merge as a `merged` line does; `abk tags` and `abk check`
    print them. A line on the change's own group is left to the error."""
    groups, _ = validate_tasks(path, repos=repos, projects=projects)
    own = {g.number: g.repo for g in groups}
    return [
        f"{path}:line {need.line}: info: group {group}: Needs: {need.change} group {need.group} "
        "is in another repository, so it waits for the merge"
        for group, found in group_needs(path).items()
        for need in found
        if not need.merged
        and not names_own_change(need, path)
        and (repo := _needed_repo(need, changes_dir, repos, projects))
        and repo != own.get(group)
    ]


def old_test_kind_warnings(path: Path) -> list[str]:
    """One notice per group heading of a tasks file that is tagged with an old test-kind tag,
    as `abk tags` and `abk check` print it."""
    warnings: list[str] = []
    for index, text in enumerate(path.read_text().splitlines(), start=1):
        found = GROUP_HEADING.match(text)
        if found and is_old_spelling(Place.TAG, found["tier"]):
            where = f"{path}:line {index}: group {found['number']}"
            warnings.append(notice(Place.TAG, found["tier"], where))
    return warnings


def redundant_separate_warnings(path: Path) -> list[str]:
    """One warning per `Separate:` line inside an `[e2e-test]` group of a tasks file: such a group
    always has a unit of its own, as `abk tags` and `abk check` print it."""
    warnings: list[str] = []
    current: re.Match[str] | None = None
    for index, text in enumerate(path.read_text().splitlines(), start=1):
        if heading := GROUP_HEADING.match(text):
            current = heading
        elif current and SEPARATE_LINE.match(text.strip()):
            if current_tag(current["tier"]) == TestTier.E2E_TEST:
                warnings.append(
                    f"{path}:line {index}: warning: group {current['number']}: `Separate:` is "
                    "redundant in an [e2e-test] group, which always has a unit of its own"
                )
    return warnings


def _group_parents(groups: list[TaskGroup]) -> dict[int, list[int]]:
    """The groups each group of one change depends on, as the planner chains them: the one
    before, and past an `Independent:` group the one before that, up to one that is not; an
    `[acceptance]` or `[narrow]` group depends on every earlier group."""
    parents: dict[int, list[int]] = {}
    for position, group in enumerate(groups):
        earlier = groups[:position]
        if group.flag in ("acceptance", "narrow"):
            chosen = [g.number for g in earlier]
        elif group.independent:
            chosen = []
        else:
            chosen = []
            for before in reversed(earlier):
                chosen.append(before.number)
                if not before.independent:
                    break
        parents[group.number] = chosen
    return parents


class InvertedGroup(Frozen):
    """One direct edge onto a group that is less urgent than the group depending on it."""

    group: int
    priority: int
    needed_by: int
    needed_by_priority: int
    # The heading line of the dependent group, where a warning about the edge points.
    needed_by_line: int = 0
    # The change the depended-on group belongs to when a `Needs:` line names it; empty for
    # a group of the same change.
    change: str = ""


def inverted_groups(
    path: Path,
    changes_dir: Path,
    *,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
) -> list[InvertedGroup]:
    """Each direct edge of a tasks file, from the planner's chain and from `Needs:` lines,
    where the depended-on group has the larger priority number. A `Needs:` target that
    cannot be read gives nothing."""
    groups, _ = validate_tasks(path, repos=repos, projects=projects)
    by_number = {g.number: g for g in groups}
    parents = _group_parents(groups)
    found = [
        InvertedGroup(
            group=parent,
            priority=by_number[parent].priority,
            needed_by=group.number,
            needed_by_priority=group.priority,
            needed_by_line=group.line,
        )
        for group in groups
        for parent in parents[group.number]
        if by_number[parent].priority > group.priority
    ]
    for number, needs in group_needs(path).items():
        group = by_number.get(number)
        for need in needs:
            other = tasks_path(need.change, changes_dir)
            if group is None or names_own_change(need, path) or not other.is_file():
                continue
            other_groups, _ = validate_tasks(other, repos=repos, projects=projects)
            target = next((g for g in other_groups if g.number == need.group), None)
            if target is not None and target.priority > group.priority:
                found.append(
                    InvertedGroup(
                        group=target.number,
                        priority=target.priority,
                        needed_by=group.number,
                        needed_by_priority=group.priority,
                        needed_by_line=group.line,
                        change=need.change,
                    )
                )
    return found


def inverted_group_warnings(
    path: Path,
    changes_dir: Path,
    *,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
) -> list[str]:
    """One warning per inverted edge of a tasks file, as `abk tags` and `abk check` print it."""
    return [
        f"{path}:line {edge.needed_by_line}: warning: "
        f"{edge.change + ' ' if edge.change else ''}group {edge.group} "
        f"(priority {edge.priority}) is needed by group {edge.needed_by} "
        f"(priority {edge.needed_by_priority}): it will be promoted to "
        f"{edge.needed_by_priority}; give it Priority {edge.needed_by_priority} or lower "
        f"group {edge.needed_by}"
        for edge in inverted_groups(path, changes_dir, repos=repos, projects=projects)
    ]


def group_promotions(groups: list[TaskGroup]) -> dict[int, tuple[int, int]]:
    """For each group that a more urgent group depends on, directly or through the chain the
    planner draws, the priority it will be promoted to and the group that gives it (of equals,
    the lowest number)."""
    dependents: dict[int, list[int]] = {}
    for number, above in _group_parents(groups).items():
        for parent in above:
            dependents.setdefault(parent, []).append(number)
    by_number = {g.number: g for g in groups}
    promoted: dict[int, tuple[int, int]] = {}
    for group in groups:
        waiting = reachable(dependents.get(group.number, []), lambda n: dependents.get(n, []))
        best = min(((by_number[n].priority, n) for n in waiting), default=None)
        if best is not None and best[0] < group.priority:
            promoted[group.number] = best
    return promoted


def unrelated_parent_warnings(
    path: Path,
    changes_dir: Path,
    *,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
) -> list[str]:
    """One warning per group of a tasks file that can give a unit unrelated parents: two or
    more same-repo parents, none built on another, as `abk tags` and `abk check` print it."""
    groups, _ = validate_tasks(path, repos=repos, projects=projects)
    parents = _group_parents(groups)
    by_number = {g.number: g for g in groups}
    needs = group_needs(path)
    warnings = []
    for group in groups:
        same = [n for n in parents[group.number] if by_number[n].repo == group.repo]
        built_on = reachable((up for n in same for up in parents[n]), lambda n: parents.get(n, []))
        open_ones = [n for n in same if n not in built_on]
        independent_before = any(by_number[n].independent for n in open_ones)
        outside = [need for need in needs.get(group.number, []) if not names_own_change(need, path)]
        outside = [
            need
            for need in outside
            if _needed_repo(need, changes_dir, repos, projects) == group.repo
        ]
        if len(open_ones) >= 2 and group.flag in ("acceptance", "narrow") and independent_before:
            shape = (
                f"an [{group.flag}] group after an `Independent:` group of its repo depends on "
                "groups neither of which builds on the other"
            )
        elif len(open_ones) >= 2 and independent_before:
            shape = (
                "an `Independent:` group followed by a later group of its repo leaves "
                "parents neither of which builds on the other"
            )
        elif open_ones and outside:
            shape = (
                "a `Needs:` line to another change's group of its repo beside a predecessor "
                "in the same repo leaves parents neither of which builds on the other"
            )
        else:
            continue
        warnings.append(
            f"{path}:line {group.line}: warning: group {group.number}: {shape}; its unit "
            "can wait for a second open parent"
        )
    return warnings


def _needed_repo(
    need: Need,
    changes_dir: Path,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]],
) -> str:
    """The repo of the group a `Needs:` line names, "" when its tasks file does not say."""
    other = tasks_path(need.change, changes_dir)
    if not other.is_file():
        return ""
    groups, _ = validate_tasks(other, repos=repos, projects=projects)
    return next((g.repo for g in groups if g.number == need.group), "")


def _runbook_anchors(text: str) -> set[str]:
    """The anchors of a markdown text's headings, as a code host makes them."""
    anchors: set[str] = set()
    for line in text.splitlines():
        if heading := re.match(r"^#+\s+(?P<title>.*?)\s*#*\s*$", line):
            title = re.sub(r"[^\w\- ]", "", heading["title"].lower())
            anchors.add(title.replace(" ", "-"))
    return anchors


def manual_runbook_warnings(path: Path, root: Path) -> list[str]:
    """One warning per `Manual:` line of a tasks file whose runbook file or heading is missing
    under `root`, as `abk tags` and `abk check` print them."""
    groups, _ = validate_tasks(path)
    warnings: list[str] = []
    for step in (step for group in groups for step in group.manual_steps):
        file, _, anchor = step.runbook.partition("#")
        where = f"{path}:line {step.line}: warning: manual step `{step.slug}`:"
        if not (root / file).is_file():
            warnings.append(f"{where} runbook file {file} does not exist")
        elif anchor and anchor.lower() not in _runbook_anchors((root / file).read_text()):
            warnings.append(f"{where} {file} has no heading #{anchor}")
    return warnings


def tasks_path(change: str, changes_dir: Path) -> Path:
    return changes_dir / change / "tasks.md"


def check_tags(
    change: str,
    changes_dir: Path,
    *,
    repos: tuple[str, ...],
    projects: Mapping[str, tuple[str, ...]] | None = None,
    splits: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[list[TaskGroup], list[str]]:
    """What `abk tags <change>` runs: the change's groups and every problem found, each
    printed as the command prints it; a change with no tasks file has one problem."""
    path = tasks_path(change, changes_dir)
    if not path.exists():
        return [], [f"no tasks.md for change {change!r} at {path}"]
    groups, errors = validate_tasks(path, repos=repos, projects=projects, splits=splits)
    return groups, [f"{path}:{error}" for error in errors]


def main(argv: list[str] | None = None) -> int:
    from agent_build_kit.installation import load_installation

    parser = argparse.ArgumentParser(
        description="Validate an OpenSpec change's task-group tags.",
    )
    parser.add_argument("change", help="change name")
    parser.add_argument("--config", type=Path, default=None, help="the abk.yaml to use")
    args = parser.parse_args(argv)

    installation = load_installation(args.config)
    path = tasks_path(args.change, installation.changes_dir)
    if not path.exists():
        print(f"no tasks.md for change {args.change!r} at {path}", file=sys.stderr)
        return 2

    groups, errors = validate_tasks(path)

    for error in errors:
        print(f"{path}:{error}", file=sys.stderr)

    if errors:
        print(f"{len(errors)} problem(s) in {args.change}", file=sys.stderr)
        return 1

    print(f"{args.change}: {len(groups)} task group(s), all tagged")
    for group in groups:
        print(f"  {group.number}. [{group.tag}] [{group.tier}] {group.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
