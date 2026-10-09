"""The review of a unit: its diff pinned to a commit, and the threads, summary and
decision a reviewer keeps against it."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.units import local_ref

THREAD_PREFIX = "ui-"
Decision = Literal["request_changes", "approve"]

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


class NoDiff(Exception):
    """The unit has nothing to diff; the message says why."""


class Reply(Frozen):
    body: str
    at: str


class Thread(Frozen):
    id: str
    path: str
    side: Literal["old", "new"]
    line: int | None
    start_line: int | None = None
    commit: str
    body: str
    at: str
    replies: tuple[Reply, ...] = ()
    resolved: bool = False
    outdated: bool = False


class Verdict(Frozen):
    round: int
    decision: Decision
    summary: str
    at: str


class Review(Frozen):
    threads: tuple[Thread, ...] = ()
    decisions: tuple[Verdict, ...] = ()


class UnitDiff(Frozen):
    commit: str
    base: str
    base_commit: str
    patch: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _resolve(repo: Path, *refs: str) -> str | None:
    """The commit the first of `refs` names in `repo`, or None."""
    for ref in refs:
        found = git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
        if found.returncode == 0:
            return found.stdout.strip()
    return None


def branch_tip(repo: Path, branch: str) -> str | None:
    return _resolve(repo, branch, f"origin/{branch}") if branch else None


def unit_diff(repo: Path, *, base: str, branch: str, commit: str | None = None) -> UnitDiff:
    """The unit's own work: `branch` (or the pinned `commit`) against the point
    where it left `base`, so work the base gained since is not shown."""
    tip = _resolve(repo, commit) if commit else branch_tip(repo, branch)
    if tip is None:
        raise NoDiff(f"the branch {branch or '(none)'} is not in the checkout")
    base_tip = _resolve(repo, local_ref(base), base)
    if base_tip is None:
        raise NoDiff(f"the base {base} is not in the checkout")
    fork = git(repo, "merge-base", base_tip, tip).stdout.strip()
    patch = git(repo, "diff", "--no-renames", fork, tip).stdout
    return UnitDiff(commit=tip, base=base, base_commit=fork, patch=patch)


def _moved(repo: Path, thread: Thread, line: int | None, tip: str) -> int | None:
    """Where `line` of `thread`'s file at its commit is at `tip`, None where it was changed."""
    if line is None:
        return None
    patch = git(
        repo, "diff", "-U0", "--no-renames", thread.commit, tip, "--", thread.path, check=False
    ).stdout
    shift = 0
    for match in _HUNK.finditer(patch):
        start, count, _, new_count = match.groups()
        first, old_n = int(start), 1 if count is None else int(count)
        new_n = 1 if new_count is None else int(new_count)
        if old_n == 0:
            if first < line:
                shift += new_n
        elif first + old_n <= line:
            shift += new_n - old_n
        elif first <= line:
            return None
    return line + shift


def placed(repo: Path, thread: Thread, tip: str | None) -> Thread:
    """`thread` as it stands at the branch tip: outdated when the branch moved
    past its commit, at its line where the lines still match."""
    if tip is None or tip == thread.commit:
        return thread
    if thread.side == "old":
        return thread.model_copy(update={"outdated": True})
    line = _moved(repo, thread, thread.line, tip)
    start = _moved(repo, thread, thread.start_line, tip)
    if line is None or (thread.start_line is not None and start is None):
        return thread.model_copy(update={"outdated": True, "line": None, "start_line": None})
    return thread.model_copy(update={"outdated": True, "line": line, "start_line": start})


class ReviewStore:
    """Every unit's review, one file each in the state directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, unit_id: str) -> Path:
        return self._directory / f"{unit_id.replace('/', '-')}.json"

    def read(self, unit_id: str) -> Review:
        path = self._path(unit_id)
        if not path.exists():
            return Review()
        return Review.model_validate(json.loads(path.read_text()))

    def _update(self, unit_id: str, change) -> object:
        path = self._path(unit_id)
        with file_lock(path.with_suffix(".lock")):
            review, result = change(self.read(unit_id))
            temporary = path.with_suffix(".tmp")
            temporary.write_text(review.model_dump_json(indent=2))
            temporary.replace(path)
        return result

    def add_thread(
        self,
        unit_id: str,
        *,
        path: str,
        side: Literal["old", "new"],
        line: int,
        start_line: int | None,
        commit: str,
        body: str,
    ) -> Thread:
        thread = Thread(
            id=f"{THREAD_PREFIX}{uuid.uuid4().hex[:12]}",
            path=path,
            side=side,
            line=line,
            start_line=start_line,
            commit=commit,
            body=body,
            at=_now(),
        )
        self._update(
            unit_id, lambda r: (r.model_copy(update={"threads": (*r.threads, thread)}), None)
        )
        return thread

    def _change_thread(self, unit_id: str, thread_id: str, change) -> Thread | None:
        def apply(review: Review) -> tuple[Review, Thread | None]:
            found = next((t for t in review.threads if t.id == thread_id), None)
            if found is None:
                return review, None
            changed = change(found)
            threads = tuple(changed if t.id == thread_id else t for t in review.threads)
            return review.model_copy(update={"threads": threads}), changed

        return self._update(unit_id, apply)  # type: ignore[return-value]

    def reply(self, unit_id: str, thread_id: str, body: str) -> Thread | None:
        return self._change_thread(
            unit_id,
            thread_id,
            lambda t: t.model_copy(update={"replies": (*t.replies, Reply(body=body, at=_now()))}),
        )

    def resolve(self, unit_id: str, thread_id: str, resolved: bool) -> Thread | None:
        return self._change_thread(
            unit_id, thread_id, lambda t: t.model_copy(update={"resolved": resolved})
        )

    def decide(
        self, unit_id: str, *, round: int, decision: Decision, summary: str
    ) -> Verdict | None:
        """Record the round's decision; None when the round already has one."""
        verdict = Verdict(round=round, decision=decision, summary=summary, at=_now())

        def apply(review: Review) -> tuple[Review, Verdict | None]:
            if any(d.round == round for d in review.decisions):
                return review, None
            return review.model_copy(update={"decisions": (*review.decisions, verdict)}), verdict

        return self._update(unit_id, apply)  # type: ignore[return-value]
