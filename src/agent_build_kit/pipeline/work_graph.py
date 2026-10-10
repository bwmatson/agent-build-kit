"""Task-group tags: parsing and validation.

An OpenSpec change's `tasks.md` is the input the runner turns into units of
work. Two facts have to be on every task group for that to be possible: the
repo the group's code lands in, and the test tier it needs. They are written
as a tagged heading:

    ## 2. [app] [tier2] Relay the archived event to the new consumer

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
from pathlib import Path

from agent_build_kit.config import active
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.units import Priority


def known_repos() -> tuple[str, ...]:
    """The repos a unit can land in: the active workspace's, as a closed set.

    Closed rather than anything that looks like a name: a near-miss (a
    capital, an underscore for a hyphen) would otherwise reach the runner and
    fail there instead of here. Empty when no workspace is loaded, which turns
    the check off rather than failing every heading.
    """
    return tuple(active().repos)


# tier1 runs on GitHub Actions; tier2 needs the live local stack on this host
# and is serialized behind one lock (docs/architecture.md).
TIERS = ("tier1", "tier2")

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

# "Acceptance: none — a refactor, nothing a consumer sees changes": a change
# with no surface to exercise, and the reason, which is what gets reviewed.
ACCEPTANCE_OPT_OUT = re.compile(r"^Acceptance:\s*none\b\s*[—–-]*\s*(?P<reason>.*?)\s*$", re.I)

# "## 2. [app] [tier2] Relay the archived event" — the tags are required, so a
# heading missing them doesn't match and is reported rather than skipped.
GROUP_HEADING = re.compile(
    r"^##\s+(?P<number>\d+)\.\s+\[(?P<repo>[^\]]*)\]\s+\[(?P<tier>[^\]]*)\]"
    r"(?:\s+\[(?P<flag>[^\]]*)\])?\s+(?P<title>.+?)\s*$"
)
ANY_GROUP_HEADING = re.compile(r"^##\s+(?P<rest>.+?)\s*$")

# "Needs: feature group 2 — why", inside a group: that group cannot pass until
# a group of *another* change has. The planner orders groups within a change;
# across changes it only sees what is already in flight, and its answer is a
# model's, so a dependency that must hold is written down and applied as code.
# A single word `merged` straight after the group number makes it wait for the
# merge; anywhere else the word is part of the reason.
NEEDS_LINE = re.compile(
    r"^Needs:\s*(?P<change>[a-z0-9][a-z0-9-]*)\s+group\s+(?P<group>\d+)\b"
    r"(?:\s+(?P<merged>merged)(?=\s|$))?\s*[—–-]*\s*(?P<reason>.*?)\s*$",
    re.I,
)

_CHECKBOX = re.compile(r"^(\s*-\s*\[)[ xX](\])", re.MULTILINE)


def specification_text(text: str) -> str:
    """A tasks file's text with progress stripped out.

    What a re-plan should key on is what the change *asks for*, not how much
    of it is done. The pipeline ticks these boxes as units land, and hashing
    the raw file would re-plan on every tick — with the planner then seeing
    the work marked done and proposing a graph that built no groups at all.
    """
    # `Needs:` lines too: they only add dependencies, which `link_needs`
    # applies on its own. Re-planning a change for one would be a model call
    # that can reshuffle units already built. Blank lines go with them: a
    # `Needs:` line comes with the blank line that sets it off.
    stripped = _CHECKBOX.sub(r"\1 \2", text)
    return "\n".join(
        line
        for line in stripped.splitlines()
        if line.strip() and not NEEDS_LINE.match(line.strip())
    )


# "Separate: reviewed and reverted on its own", inside a group: no other change's
# groups are joined to its unit and it is never joined to another. The reason is
# what review agrees to, as with `Acceptance: none`.
SEPARATE_LINE = re.compile(r"^Separate:\s*(?P<reason>.*?)\s*$", re.I)

# "Independent: only adds a receiver", inside a group: it depends on no earlier
# group of its change. The reason is what review agrees to.
INDEPENDENT_LINE = re.compile(r"^Independent:\s*(?P<reason>.*?)\s*$", re.I)

# "Priority: 2", inside a group: how urgent its unit is, 1 (most) to 5, 3 when
# unsaid. Above the first group it is the default for the change's groups.
PRIORITY_LINE = re.compile(r"^Priority:\s*(?P<value>.*?)\s*$", re.I)
PRIORITY_VALUE = re.compile(r"[1-5]")

# "- [ ] 1.1 Do the thing" / "- [x] 1.1 Done". Checked and unchecked both count:
# this asks whether a group has tasks at all, not how far along it is.
TASK_LINE = re.compile(r"^\s*-\s+\[[ xX]\]\s+\d+\.\d+\s+\S")


class TaskGroup(Frozen):
    """One `## N. [repo] [tier] Title` group and the tasks under it."""

    number: int
    repo: str
    tier: str
    title: str
    line: int
    task_count: int
    # "contract", "narrow", "acceptance", or "" — see FLAGS.
    flag: str = ""
    # A `Separate: <reason>` line in the group: never carried by another
    # change's unit, and no other change's groups are added to its unit.
    separate: bool = False
    # An `Independent: <reason>` line in the group: it depends on no earlier
    # group of its change.
    independent: bool = False
    # 1 (most urgent) to 5, from a `Priority:` line in the group or above the first.
    priority: int = Priority.NORMAL
    # The "Done when" sentence under the heading, "" when the group has none.
    goal: str = ""


class ValidationError(Frozen):
    """Something a human has to fix in tasks.md, with where to find it."""

    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def validate_tasks(
    path: Path, *, repos: tuple[str, ...] | None = None
) -> tuple[list[TaskGroup], list[ValidationError]]:
    """Parse a change's tasks.md and report everything wrong with its groups.

    Returns the groups it could parse and every error found. All errors are
    collected rather than raising on the first, so one CI run shows the whole
    list instead of one problem per push.
    """
    repos = known_repos() if repos is None else repos
    lines = path.read_text().splitlines()

    groups: list[TaskGroup] = []
    errors: list[ValidationError] = []
    tasks_seen: list[int] = []
    heading_lines: list[int] = []
    separate: set[int] = set()
    independent: dict[int, int] = {}
    current: int | None = None
    default_priority: int | None = None
    priorities: dict[int, int] = {}
    stray_priority: dict[int, int] = {}

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
                            "from 1 (most urgent) to 5",
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
            if (
                current is not None
                and (need := NEEDS_LINE.match(text.strip()))
                and need["merged"]
                and need["change"].lower() == path.parent.name.lower()
            ):
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
        heading_lines.append(index)
        tasks_seen.append(0)

        tagged = GROUP_HEADING.match(text)
        if tagged is None:
            errors.append(
                ValidationError(
                    line=index,
                    message=f'group "{heading.group("rest")}" is missing its tags — '
                    f"headings are `## <n>. [<repo>] [<tier>] <title>`, "
                    f"repo one of {', '.join(repos) or '<the workspace repos>'}, "
                    f"tier one of {', '.join(TIERS)}",
                )
            )
            continue

        repo, tier = tagged.group("repo"), tagged.group("tier")
        number = int(tagged.group("number"))

        if repos and repo not in repos:
            errors.append(
                ValidationError(
                    line=index,
                    message=f'group {number} has unknown repo "{repo}" — '
                    f"expected one of {', '.join(repos)}",
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

        if tier not in TIERS:
            errors.append(
                ValidationError(
                    line=index,
                    message=f'group {number} has unknown tier "{tier}" — '
                    f"expected one of {', '.join(TIERS)}",
                )
            )
            continue

        groups.append(
            TaskGroup(
                number=number,
                repo=repo,
                tier=tier,
                title=tagged.group("title"),
                line=index,
                task_count=0,
                flag=flag or "",
            )
        )

    # task_count is only known once the following lines have been read, so the
    # groups are rebuilt here rather than mutated in place.
    counts = dict(zip(heading_lines, tasks_seen, strict=True))
    groups = [
        TaskGroup(
            number=g.number,
            repo=g.repo,
            tier=g.tier,
            title=g.title,
            line=g.line,
            task_count=counts[g.line],
            flag=g.flag,
            goal=_goal(lines, g.line),
            separate=g.line in separate,
            independent=g.line in independent,
            priority=priorities.get(
                g.line, Priority.NORMAL if default_priority is None else default_priority
            ),
        )
        for g in groups
    ]

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
    if any(g.flag == "contract" for g in groups):
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
                    "`[tier2] [acceptance]` group that drives what it built the way its "
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
            "drives the change on the stack, so it is tier2",
        )
        for g in accepting
        if g.tier != "tier2"
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


def group_needs(path: Path) -> dict[int, list[Need]]:
    """Each group's `Needs:` lines with their `merged` qualifier and reason."""
    needs: dict[int, list[Need]] = {}
    current: int | None = None
    for line in path.read_text().splitlines():
        if heading := GROUP_HEADING.match(line):
            current = int(heading["number"])
        elif current is not None and (found := NEEDS_LINE.match(line.strip())):
            needs.setdefault(current, []).append(
                Need(
                    change=found["change"].lower(),
                    group=int(found["group"]),
                    merged=found["merged"] is not None,
                    reason=found["reason"],
                )
            )
    return needs


def tasks_path(change: str, changes_dir: Path) -> Path:
    return changes_dir / change / "tasks.md"


def check_tags(
    change: str, changes_dir: Path, *, repos: tuple[str, ...]
) -> tuple[list[TaskGroup], list[str]]:
    """What `abk tags <change>` runs: the change's groups and every problem found, each
    printed as the command prints it; a change with no tasks file has one problem."""
    path = tasks_path(change, changes_dir)
    if not path.exists():
        return [], [f"no tasks.md for change {change!r} at {path}"]
    groups, errors = validate_tasks(path, repos=repos)
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
        print(f"  {group.number}. [{group.repo}] [{group.tier}] {group.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
