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
NEEDS_LINE = re.compile(
    r"^Needs:\s*(?P<change>[a-z0-9][a-z0-9-]*)\s+group\s+(?P<group>\d+)\b", re.I
)

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

    for index, text in enumerate(lines, start=1):
        if TASK_LINE.match(text):
            if tasks_seen:
                tasks_seen[-1] += 1
            continue

        heading = ANY_GROUP_HEADING.match(text)
        if heading is None:
            continue

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
        )
        for g in groups
    ]

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


def cross_change_needs(path: Path) -> dict[int, list[tuple[str, int]]]:
    """Each group's `Needs:` lines: {group: [(other change, its group), ...]}."""
    needs: dict[int, list[tuple[str, int]]] = {}
    current: int | None = None
    for line in path.read_text().splitlines():
        if heading := GROUP_HEADING.match(line):
            current = int(heading["number"])
        elif current is not None and (found := NEEDS_LINE.match(line.strip())):
            needs.setdefault(current, []).append((found["change"].lower(), int(found["group"])))
    return needs


def tasks_path(change: str, changes_dir: Path) -> Path:
    return changes_dir / change / "tasks.md"


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
