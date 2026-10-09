"""Reviews made in the web UI as a comment source for the poller, the agent's replies
written back into the threads they answer, and the diff hunk on a review note."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from agent_build_kit.forges import PullRequest, ReviewNote
from agent_build_kit.pipeline import pr_replies
from agent_build_kit.pipeline.pr_poller import ListPrs
from agent_build_kit.pipeline.units import base_of
from agent_build_kit.serve.review import (
    THREAD_PREFIX,
    NoDiff,
    Review,
    ReviewStore,
    Thread,
    branch_tip,
    placed,
    unit_diff,
)

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation
    from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore

_HUNK_HEAD = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DECISIONS = {"request_changes": "changes_requested", "approve": "approved"}
# Beside the line the agent's prompt marks the comment on, in the hunk it prints.
_MARK = "  <- comment"


def reply_id(thread: Thread, number: int) -> str:
    """The id of a thread's `number`th reply (from 1): the thread's id and the count, so it
    cannot be taken for one of the host's, and a reply can be traced to its thread."""
    return f"{thread.id}.{number}"


def decision_id(round: int) -> str:
    """The id of the request for changes made in `round`: one comment per round, so a second
    request is news to the poller though the review decision is already changes-requested."""
    return f"{THREAD_PREFIX}decision-{round}"


def with_ui_review(
    list_prs: ListPrs, *, review_of: Callable[[PullRequest], Review | None]
) -> ListPrs:
    """`list_prs` with each pull request carrying the UI review of its unit as comments,
    replies and a decision, under ids that cannot collide with the host's. The agent's own
    replies are left out."""

    def listed() -> list[PullRequest]:
        return [_with_review(pull, review_of(pull)) for pull in list_prs()]

    return listed


def _with_review(pull: PullRequest, review: Review | None) -> PullRequest:
    if review is None:
        return pull
    ids: list[str] = []
    bodies: list[str] = []
    for thread in review.threads:
        ids.append(thread.id)
        bodies.append(thread.body)
        for number, reply in enumerate(thread.replies, 1):
            if pr_replies.MARKER not in reply.body:
                ids.append(reply_id(thread, number))
                bodies.append(reply.body)
    for decision in sorted(review.decisions, key=lambda d: d.round):
        if decision.decision == "request_changes":
            ids.append(decision_id(decision.round))
            bodies.append(decision.summary)
    update: dict[str, object] = {}
    if ids:
        update["conversation"] = (*pull.conversation, *ids)
        update["comment_bodies"] = (*pull.comment_bodies, *bodies)
    if review.decisions:
        latest = max(review.decisions, key=lambda d: d.round)
        update["review_decision"] = _DECISIONS[latest.decision]
    return pull.model_copy(update=update) if update else pull


def write_back_replies(
    store: ReviewStore, unit_id: str, replies: Sequence[pr_replies.Reply]
) -> list[str]:
    """Write each reply, marked as the pipeline's, into the thread its comment id names (a
    thread's or one of its replies'). Returns the ids written."""
    written: list[str] = []
    for reply in replies:
        known = {t.id for t in store.read(unit_id).threads}
        thread_id = reply.comment_id
        if thread_id not in known:
            thread_id = thread_id.rsplit(".", 1)[0]
        thread = store.reply(unit_id, thread_id, f"{reply.body}\n{pr_replies.MARKER}")
        if thread is not None:
            written.append(reply_id(thread, len(thread.replies)))
    return written


def ui_review_notes(review: Review, *, repo: Path, tip: str | None) -> list[ReviewNote]:
    """The review's threads, replies and requests for changes as notes at the branch `tip`: a
    thread's note is live while its line still exists there, at the line it has moved to; a
    request's summary is anchored nowhere."""
    notes: list[ReviewNote] = []
    for thread in review.threads:
        at = placed(repo, thread, tip)
        live = not at.outdated or (at.line is not None and at.side == "new")
        notes.append(
            ReviewNote(
                id=thread.id,
                body=thread.body,
                path=at.path,
                line=at.line,
                side=at.side,
                live=live,
            )
        )
        for number, reply in enumerate(thread.replies, 1):
            notes.append(
                ReviewNote(
                    id=reply_id(thread, number),
                    body=reply.body,
                    path=at.path,
                    line=at.line,
                    side=at.side,
                    live=live,
                )
            )
    for decision in sorted(review.decisions, key=lambda d: d.round):
        if decision.decision == "request_changes":
            notes.append(ReviewNote(id=decision_id(decision.round), body=decision.summary))
    return notes


def attach_hunks(notes: list[ReviewNote], patch: str) -> list[ReviewNote]:
    """`notes` with the hunk of `patch` holding each one's line on its side of the diff, that
    line marked; a note whose line the patch does not contain, or that has none, gets no hunk."""
    hunks = _hunks(patch)
    out = []
    for note in notes:
        found = ""
        if note.line is not None:
            for old, new, lines in hunks.get(note.path, []):
                first, count = old if note.side == "old" else new
                if first <= note.line < first + count:
                    found = _marked(lines, first, note.line, note.side)
                    break
        out.append(note.model_copy(update={"hunk": found}) if found else note)
    return out


def _marked(lines: list[str], first: int, line: int, side: str) -> str:
    """A hunk's `lines` (header first) with the one at `line` of the given side marked: a
    deleted line has an old-side number only, an added one a new-side number only."""
    skipped = "+" if side == "old" else "-"
    out = [lines[0]]
    number = first
    for text in lines[1:]:
        if text.startswith((skipped, "\\")):
            out.append(text)
            continue
        out.append(f"{text}{_MARK}" if number == line else text)
        number += 1
    return "\n".join(out)


_Span = tuple[int, int]


def _hunks(patch: str) -> dict[str, list[tuple[_Span, _Span, list[str]]]]:
    """Each file's hunks as (old first line and count, new first line and count, lines from
    `@@` on). A deleted file is under its old path."""
    files: dict[str, list[tuple[_Span, _Span, list[str]]]] = {}
    path = ""
    old_path = ""
    current: list[str] = []

    def close() -> None:
        head = _HUNK_HEAD.match(current[0]) if current else None
        if head and path:
            old = (int(head.group(1)), 1 if head.group(2) is None else int(head.group(2)))
            new = (int(head.group(3)), 1 if head.group(4) is None else int(head.group(4)))
            files.setdefault(path, []).append((old, new, list(current)))
        current.clear()

    for line in patch.splitlines():
        if line.startswith("diff --git "):
            close()
            path = old_path = ""
        elif line.startswith("--- ") and not current:
            old_path = "" if line == "--- /dev/null" else line[4:].removeprefix("a/")
        elif line.startswith("+++ ") and not current:
            path = old_path if line == "+++ /dev/null" else line[4:].removeprefix("b/")
        elif line.startswith("@@ "):
            close()
            current.append(line)
        elif current:
            current.append(line)
    close()
    return files


def ui_reply_writer(
    state_dir: Path, units: UnitStore
) -> Callable[[str, int, Sequence[pr_replies.Reply]], list[str]]:
    """What `pr_replies.build_post_replies` hands the replies to UI comments: written into the
    review of the unit that owns the pull request (its repo name and number), and the ids
    written returned. A pull request with no unit takes none."""
    store = ReviewStore(state_dir / "reviews")

    def write(repo: str, pr: int, replies: Sequence[pr_replies.Reply]) -> list[str]:
        unit = unit_of(units, repo, pr)
        return write_back_replies(store, unit.id, replies) if unit else []

    return write


def unit_of(store: UnitStore, repo: str, pr: int) -> StoredUnit | None:
    """The unit whose pull request is number `pr` of the repo named `repo`."""
    return next((u for u in store.all() if u.repo == repo and u.pr == pr), None)


def ui_notes_of(inst: Installation, store: UnitStore) -> Callable[[str, int], list[ReviewNote]]:
    """The notes of the review made in the web UI on a pull request (its repo name and number),
    placed at the unit's branch tip; none for a pull request with no unit or no review."""

    def notes(repo: str, pr: int) -> list[ReviewNote]:
        unit = unit_of(store, repo, pr)
        checkout = inst.checkouts.get(repo)
        if unit is None or checkout is None or not checkout.is_dir():
            return []
        review = ReviewStore(inst.state_dir / "reviews").read(unit.id)
        return ui_review_notes(review, repo=checkout, tip=branch_tip(checkout, unit.branch))

    return notes


def unit_patch_of(inst: Installation, store: UnitStore) -> Callable[[str, int], str]:
    """The unit's own diff, taken against the base it builds on, as the review tab shows it;
    empty where the unit, its checkout or its branch is not there to diff."""

    def patch(repo: str, pr: int) -> str:
        unit = unit_of(store, repo, pr)
        checkout = inst.checkouts.get(repo)
        if unit is None or checkout is None or not checkout.is_dir() or not unit.branch:
            return ""
        try:
            return unit_diff(checkout, base=base_of(unit, store.all()), branch=unit.branch).patch
        except NoDiff:
            return ""

    return patch
