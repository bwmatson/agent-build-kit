"""The PR description: everything a reviewer needs in one place.

On a free-plan private repo GitHub enforces nothing — no required checks, no
blocked merge, no approval state. The PR body is therefore not decoration; it
is the only place where the stack position, the test evidence and the
provisional parts of the work come together where a human will see them
(docs/architecture.md).

Three things it must always say:

- **Where this sits in the stack,** because merging out of order is the
  easiest mistake to make — unless the host renders the stack itself, when the
  body says only whether the chain is linear, which the host does not.
- **What it assumes,** since a unit stacked on unmerged work is built on
  something that may still change.
- **How it was verified,** including the e2e-test snapshot, which no CI run can
  reproduce.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.budget import Section, cut_head, cut_tail, fit
from agent_build_kit.config import active
from agent_build_kit.forges.base import fit_description
from agent_build_kit.installation import changes_dir_under
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.unit_store import BriefEntry, Description, E2eState, StoredUnit
from agent_build_kit.pipeline.units import (
    MERGED,
    Member,
    as_shown,
    through_satisfied,
    trunk_of,
)
from agent_build_kit.pipeline.verdict import GateResult, TierVerdict, VerdictFacts
from agent_build_kit.pipeline.work_graph import TaskGroup, validate_tasks


def _unmerged(unit: StoredUnit, graph: list[StoredUnit]) -> list[StoredUnit]:
    """What this unit depends on that has not merged yet."""
    index = {item.id: item for item in graph}
    direct = as_shown(unit, graph)
    return [
        index[dep]
        for dep in through_satisfied(direct, graph)
        if dep in index and index[dep].state != MERGED
    ]


def stack_line(unit: StoredUnit, graph: list[StoredUnit], *, base: str) -> str:
    """One line describing what this PR sits on, and whether it may merge."""
    unmerged = _unmerged(unit, graph)

    if not unmerged:
        return (
            f"Based on `{base}`, with nothing unmerged beneath it — "
            "**ready to merge** whenever the checks look right."
        )

    parents = ", ".join(
        f"`{parent.id}`" + (f" (#{parent.pr})" if parent.pr else "") for parent in unmerged
    )
    return (
        f"Stacked on `{base}`. **Merge {parents} first** — merging this one "
        "ahead of them would pull their commits in with it."
    )


def assumptions(unit: StoredUnit, graph: list[StoredUnit], trunk: str = "main") -> str:
    """The PR body's statement of what the unit assumes about the units beneath it:
    which are still unmerged, or that nothing is."""
    unmerged = _unmerged(unit, graph)

    if not unmerged:
        return (
            f"This unit assumes nothing unmerged: everything it builds on is already in `{trunk}`."
        )

    lines = []
    for parent in unmerged:
        where = f"#{parent.pr}" if parent.pr else "not yet opened"
        lines.append(
            f"- Builds on `{parent.id}` ({parent.repo}, {where}), which has not merged yet. "
            "If that PR changes in review, this one is restacked and re-verified."
        )
    return "\n".join(lines)


def _change_path(change: str) -> str:
    """Where a change's files are, under the planning repo."""
    return (changes_dir_under(Path(), active().planning.specs_dir) / change).as_posix()


def _scope_lines(unit: StoredUnit) -> str:
    """What the unit builds: each change with its groups, and where its spec is."""
    first, *carried = unit.members()
    groups = ", ".join(str(group) for group in first.groups) or "—"
    lines = [
        f"Unit `{unit.id}` of change **{first.change}**, task group(s) {groups}.",
        f"Spec: `{_change_path(first.change)}/` in the planning repo.",
    ]
    for member in carried:
        numbers = ", ".join(str(group) for group in member.groups)
        lines.append(
            f"Also carries task group(s) {numbers} of change **{member.change}**. "
            f"Spec: `{_change_path(member.change)}/` in the planning repo."
        )
    return "\n".join(lines)


_OUTPUT_CUT = "_(earlier output trimmed to fit the host's description limit)_"
_OUTPUT_GONE = "_The full output was trimmed: it did not fit the host's description limit._"


def _output_parts(verification: str) -> tuple[str, str, str, int, int] | None:
    """The e2e-test section split around its output: what precedes the output,
    the output, what follows it, and where the details block starts and ends."""
    start = verification.find("<details>")
    end = verification.rfind("</details>")
    opened = verification.find("```\n", start) if start != -1 else -1
    closed = verification.rfind("\n```", 0, end) if end != -1 else -1
    if min(start, end, opened, closed) == -1 or closed < opened + 4:
        return None
    return (
        verification[: opened + 4],
        verification[opened + 4 : closed],
        verification[closed:],
        start,
        end + len("</details>"),
    )


def _fixed(key: str, text: str) -> Section:
    """A part of the description that is never shrunk or dropped."""
    return Section(
        key=key, render=lambda size: text, natural=len(text), smallest=len(text), required=True
    )


def _verification_section(verification: str) -> Section:
    """The verification part. Its e2e-test output is what shrinks, by keeping the
    tail on a line boundary; its smallest form keeps the results and says the
    output was trimmed."""
    verification = verification.rstrip("\n")
    parts = _output_parts(verification)
    if parts is None:
        return _fixed("verification", verification)
    head, output, tail, start, end = parts
    gone = verification[:start] + _OUTPUT_GONE + verification[end:]

    def render(size: int) -> str:
        if size >= len(verification):
            return verification
        room = size - len(head) - len(tail)
        if room <= len(_OUTPUT_CUT):
            return gone
        cut = cut_tail(output, room, "line", marker=_OUTPUT_CUT)
        # A cut that kept no output line is a bare or clipped marker: say it with `gone`.
        return head + cut + tail if cut.startswith(f"{_OUTPUT_CUT}\n\n") else gone

    return Section(
        key="verification",
        render=render,
        natural=len(verification),
        smallest=len(gone),
        weight=1,
        required=True,
    )


def _follow_ups_section(follow_ups: Sequence[str]) -> Section:
    """The follow-ups: whole items in order, then a count of those left out;
    the smallest form is the count alone."""

    def block(shown: int) -> str:
        more = len(follow_ups) - shown
        return (
            "## Left for later\n\nApproved, with these recorded rather than blocking:\n\n"
            + "\n".join(f"- {item}" for item in follow_ups[:shown])
            + (f"{chr(10) * 2 if shown else ''}_…and {more} more._" if more else "")
        )

    def render(size: int) -> str:
        for shown in range(len(follow_ups), 0, -1):
            if len(block(shown)) <= size:
                return block(shown)
        return block(0)

    return Section(
        key="follow_ups",
        render=render,
        natural=len(block(len(follow_ups))),
        smallest=len(block(0)),
        weight=2,
    )


# The new sections outweigh the process text, so they are the last to be reduced.
_PURPOSE_WEIGHT = 8

_WHY_SECTION = re.compile(r"^##[ \t]+Why[ \t]*\n(.*?)(?=^##[ \t]|\Z)", re.M | re.S)
_LOCATED = re.compile(r"^(?P<file>[\w./-]*[./][\w./-]*?)(?::\d+)? — ")
_PATH = re.compile(r"[\w-]+(?:/[\w.-]+)+|[\w-]+\.\w+")


def _why_text(changes_dir: Path, change: str) -> str:
    """The proposal's `Why` text, empty when it cannot be read or has none."""
    try:
        proposal = (changes_dir / change / "proposal.md").read_text()
    except OSError:
        return ""
    found = _WHY_SECTION.search(proposal)
    return found[1].strip() if found else ""


def _groups_of(changes_dir: Path, change: str) -> list[TaskGroup]:
    try:
        return validate_tasks(changes_dir / change / "tasks.md")[0]
    except OSError:
        return []


def _why_block(label: str, text: str, marker: str) -> Section:
    """One change's reason: its label and text, the text cut at a paragraph to the
    room given, down to the pointer alone."""
    full = "\n\n".join(part for part in (label, text) if part)
    pointer = "\n\n".join(part for part in (label, marker) if part)

    def render(size: int) -> str:
        if size >= len(full):
            return full
        room = size - len(label) - 2 * bool(label)
        return "\n\n".join(
            part for part in (label, cut_head(text, room, "paragraph", marker=marker)) if part
        )

    return Section(
        key="why-block", render=render, natural=len(full), smallest=len(pointer), weight=1
    )


def _why_section(changes_dir: Path, members: Sequence[Member], ceiling: int) -> Section | None:
    """The reason for each change the unit builds: its proposal's Why, cut at a
    paragraph to the ceiling with a pointer to the proposal; the smallest form is
    the pointers alone. Room one change's reason leaves unused goes to the others."""
    blocks: list[Section] = []
    for member in members:
        text = _why_text(changes_dir, member.change)
        if not text:
            continue
        numbers = {group.number for group in _groups_of(changes_dir, member.change)}
        label = ""
        if numbers - set(member.groups):
            label = (
                f"_This pull request builds part of change **{member.change}**; "
                "this is the change's reason._"
            )
        elif len(members) > 1:
            label = f"_Change **{member.change}**:_"
        marker = f"_… The full reason is in `{_change_path(member.change)}/proposal.md`._"
        blocks.append(
            _why_block(label, cut_head(text, ceiling, "paragraph", marker=marker), marker)
        )
    if not blocks:
        return None

    parts = [_fixed("heading", "## Why"), *blocks]

    def render(size: int) -> str:
        return fit(parts, size)

    return Section(
        key="why",
        render=render,
        natural=sum(part.natural for part in parts) + 2 * len(blocks),
        smallest=sum(part.smallest for part in parts) + 2 * len(blocks),
        weight=_PURPOSE_WEIGHT,
        required=True,
    )


_WHAT_HEADING = "## What this pull request does"
# What the reviewer's text may take of the description, whatever it wrote.
_MAX_CHANGES = 6
_MAX_CHANGE_CHARS = 300
_MAX_SUMMARY_CHARS = 400


def _capped(text: str, size: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1] + "…"


def _changes_section(described: Description) -> Section | None:
    """The reviewer's core changes as bullets, with its summary leading them.

    The text is the model's, so it is capped. When the room is short the summary
    goes first, then bullets from the end with a count of those left out; the
    smallest form is the first bullet."""
    bullets = [
        f"- {_capped(change, _MAX_CHANGE_CHARS)}" for change in described.changes if change.strip()
    ][:_MAX_CHANGES]
    if not bullets:
        return None
    summary = _capped(described.summary, _MAX_SUMMARY_CHARS)

    def block(shown: int, *, lead: bool) -> str:
        more = len(bullets) - shown
        parts = [summary if lead and summary else "", "\n".join(bullets[:shown])]
        if more:
            parts.append(f"_…and {more} more._")
        return "\n\n".join(part for part in parts if part)

    def render(size: int) -> str:
        for shown in range(len(bullets), 0, -1):
            for lead in (True, False):
                if len(block(shown, lead=lead)) <= size:
                    return block(shown, lead=lead)
        return cut_head(bullets[0], size, "char")

    return Section(
        key="changes",
        render=render,
        natural=len(block(len(bullets), lead=True)),
        smallest=len(bullets[0]),
        weight=_PURPOSE_WEIGHT,
        required=True,
    )


def _purpose_sections(
    changes_dir: Path, members: Sequence[Member], described: Description | None = None
) -> list[Section]:
    """What the pull request does: the goal of each group the unit builds, kept
    whole, then the core changes the reviewer last described, which shrink."""
    goals = [
        group.goal
        for member in members
        for group in _groups_of(changes_dir, member.change)
        if group.number in member.groups and group.goal
    ]
    changes = _changes_section(described) if described is not None else None
    if not goals and changes is None:
        return []
    text = "\n\n".join([_WHAT_HEADING, *goals])
    return [
        Section(
            key="goal",
            render=lambda size: text,
            natural=len(text),
            smallest=len(text),
            weight=_PURPOSE_WEIGHT,
            required=True,
        ),
        *([changes] if changes else []),
    ]


def _once_each(points: Sequence[str]) -> list[str]:
    """The follow-ups with each point listed one time, in its located form.

    The reviewer records a point twice when it gives it as an optional finding
    (`file:line — summary`) and again as a free-text follow-up, in words of its own,
    so the two are paired by the file they name: a bare point that names a file an
    optional finding locates is that finding again. A bare point that names no such
    file is kept."""
    located = {found["file"] for point in points if (found := _LOCATED.match(point))}
    return [
        point
        for point in points
        if _LOCATED.match(point)
        or not any(path.rstrip(".:,;") in located for path in _PATH.findall(point))
    ]


def verified_list(facts: VerdictFacts | None, rounds: int | None) -> str:
    """What the pipeline itself checked, from the unit's recorded results: each one listed,
    a result that is not recorded as not recorded."""
    facts = facts or VerdictFacts(kind=TestTier.UNIT_TEST)
    lines = [
        "- Tests were committed first and seen to fail first."
        if facts.red_first == GateResult.PASSED
        else "- The failing run before the implementation: failed"
        if facts.red_first == GateResult.FAILED
        else "- The failing run before the implementation: not recorded",
        _result_line("unit-test", facts.unit_test),
    ]
    if facts.kind == TestTier.E2E_TEST:
        if facts.e2e_state == E2eState.DEFERRED:
            lines.append("- e2e-test result: deferred to verify")
        elif facts.e2e_state is None:
            lines.append(_result_line("e2e-test", None))
        else:
            failed = facts.e2e_state == E2eState.FAILED
            lines.append(
                _result_line("e2e-test", GateResult.FAILED if failed else GateResult.PASSED)
            )
    if rounds is None:
        lines.append("- Rounds of review: not recorded")
    else:
        lines.append(f"- Review took {rounds} review round{'s' * (rounds != 1)}")
    return "\n".join(lines)


def _result_line(name: str, result: GateResult | None) -> str:
    if result in (GateResult.PASSED, GateResult.FAILED):
        return f"- {name} result: {result.value}"
    return f"- {name} result: not recorded"


# The caps on the reviewer's lists, so the section stays small under the smallest host limit.
_MAX_BRIEF_ENTRIES = 5
_MAX_PLACE_CHARS = 100
_MAX_REASON_CHARS = 160


def _entry_lines(entries: Sequence[BriefEntry]) -> str:
    named = [entry for entry in entries if entry.place.strip()][:_MAX_BRIEF_ENTRIES]
    return "\n".join(
        f"- `{_capped(entry.place, _MAX_PLACE_CHARS).replace('`', "'")}` — "
        f"{_capped(entry.reason, _MAX_REASON_CHARS)}"
        for entry in named
    )


def _start_here(
    described: Description | None,
    facts: VerdictFacts | None,
    rounds: int | None,
    verdict: TierVerdict | None,
) -> Section:
    """The section a person reads first: where to look, what to skip, what was verified, and
    the review tier. The reviewer's lists are capped and the section is never shrunk."""
    parts = ["## Start here"]
    if described is not None:
        for title, entries in (
            ("Read first", described.focus),
            ("Safe to skip", described.skippable),
        ):
            lines = _entry_lines(entries)
            if lines:
                parts.append(f"**{title}**\n\n{lines}")
    parts.append(f"**Already verified by the pipeline**\n\n{verified_list(facts, rounds)}")
    if verdict is not None and active().review.enabled:
        parts.append(f"**Review tier: `{verdict.tier.value}`** — {verdict.reason}")
    return _fixed("start_here", "\n\n".join(parts))


def build_pr_body(
    unit: StoredUnit,
    *,
    graph: list[StoredUnit],
    base: str,
    e2e_snapshot: str | None = None,
    restack_note: str | None = None,
    open_points: str | None = None,
    follow_ups: list[str] | None = None,
    stacks: bool = False,
    linear: bool = True,
    limit: int | None = None,
    changes_dir: Path | None = None,
    why_ceiling: int = 600,
    facts: VerdictFacts | None = None,
    rounds: int | None = None,
    verdict: TierVerdict | None = None,
) -> str:
    """The full description for a unit's PR."""
    if unit.e2e_state == E2eState.DEFERRED:
        verification = (
            "## Verification\n\n"
            "**e2e-test deferred to verify.** The live tests run after the merge, against the "
            "deployed change, so a failure in them is found after the merge, not before it."
        )
    elif unit.tier == TestTier.E2E_TEST:
        verification = (
            e2e_snapshot
            or "## e2e-test results\n\n_Not recorded — this PR should not have been pushed._"
        )
    else:
        ci = forges.for_repo(unit.repo)[0].ci_name
        verification = (
            "## Verification\n\n"
            "This is a **unit-test** unit: everything it needs is fakes, fixtures or "
            f"throwaway containers, so {ci} runs the whole of it. No e2e-test run was required."
        )

    # Where the host renders the stack, it shows the order and what is beneath
    # this PR; repeated here, the pipeline's copy is the one that goes stale.
    # Linearity it does not show until the merge button is disabled. On the
    # trunk there is no chain beneath to be linear or not, and `stack_line`
    # says what matters: that it is ready to merge.
    line = stack_line(unit, graph, base=base)
    beneath = _unmerged(unit, graph)
    if not beneath:
        position = line
    elif not linear:
        linearity = (
            "**The chain is not linear**: this branch no longer sits on the one below "
            "it, so it cannot be merged until the pipeline rebases it."
        )
        position = linearity if stacks else f"{line}\n\n{linearity}"
    elif stacks:
        position = "The chain beneath this is linear: this branch sits on the one below it."
    else:
        position = line
    if stacks and beneath:
        # What it is waiting for, without restating where it sits.
        position += " It merges after everything beneath it in the stack has merged."
    order = "the stack order the host shows" if stacks else "the stack order above"

    built = (
        "Tests were committed first and seen to fail before any implementation existed; "
        "the commit order is checked mechanically; lint, formatting and types pass at the tip."
    )
    footer = f"""\
## How this was built

{built}

---

_Opened by the spec-driven pipeline. It never merges its own PRs — a human
merges every one, after checking {order}._
"""
    members = unit.members()
    sections = (
        [_start_here(unit.description, facts, rounds, verdict)] if active().review.brief else []
    )
    if changes_dir is not None:
        why = _why_section(changes_dir, members, why_ceiling)
        sections += [
            *([why] if why else []),
            *_purpose_sections(changes_dir, members, unit.description),
        ]
    sections += [
        _fixed("position", position),
        _fixed("scope", _scope_lines(unit)),
        _fixed("assumptions", f"## Assumptions\n\n{assumptions(unit, graph, trunk_of(unit.repo))}"),
        _verification_section(verification),
    ]
    if restack_note:
        sections.append(_fixed("restack", f"## What moved underneath this\n\n{restack_note}"))
    if open_points:
        sections.append(
            _fixed(
                "held",
                "## Held for a person\n\nReview's rounds ran out with this still outstanding:\n\n"
                f"{open_points}",
            )
        )
    if follow_ups:
        sections.append(_follow_ups_section(_once_each(follow_ups)))
    sections.append(_fixed("footer", footer))

    if limit is None:
        return fit(sections, sum(section.natural for section in sections) + 2 * len(sections))
    # Shared by weight when over the limit; the line cut is the last guard, as
    # no host cuts a description.
    return fit_description(fit(sections, limit), limit)


def _landed_elsewhere(unit: StoredUnit, graph: Sequence[StoredUnit]) -> StoredUnit | None:
    """The same-repo predecessor whose branch already carried this unit's
    work, if the graph can say.

    A unit that reaches `satisfied` built on some base — its nearest same-repo
    dependency, looked through any satisfied one in between (`through_satisfied`,
    the same lookup `base_of` uses). That predecessor is where the work landed;
    a unit with no same-repo dependency in the graph answers None rather than
    guessing.
    """
    index = {item.id: item for item in graph}
    for dep_id in through_satisfied(unit, graph):
        dep = index.get(dep_id)
        if dep is not None and dep.repo == unit.repo:
            return dep
    return None


def satisfied_reason(unit: StoredUnit, *, graph: Sequence[StoredUnit]) -> str:
    """Why a satisfied unit's stale pull request is closing.

    Composed here, mechanically, rather than asked of a model: the judgement
    that got the unit here (no commits of its own, unit-test green at the tip) is
    already mechanical, and this is the same kind of text `build_pr_body`
    writes without a model call.
    """
    covered = " and ".join(
        f"{', '.join(str(group) for group in member.groups) or '—'} of change `{member.change}`"
        for member in unit.members()
    )
    landed = _landed_elsewhere(unit, graph)
    where = ""
    if landed is not None:
        where = f" — it landed in `{landed.id}`" + (f" (#{landed.pr})" if landed.pr else "")
    return (
        f"Task group(s) {covered} were already implemented "
        f"elsewhere{where}. There is nothing here for this pull request to add, so it is "
        "closing — its tasks are ticked in tasks.md all the same."
    )
