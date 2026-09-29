"""Answering a reviewer in the threads they opened.

A rework used to change the code and say nothing, so a reviewer resolving
their comments had to work out which commit answered which, and a question
("is there a reason these imports are in the function?") got an edit but no
answer. Now the rework agent ends with a reply per comment it acted on or
answered, and this posts them — in each comment's own thread, after the push,
so what a reply describes is already on the PR.

The agent writes the words and never touches the host: posting before the push
would describe code the reviewer cannot see, and from inside a worktree the
client runs as whichever account happens to be active, not the one owning the
repo.

What is posted here must not come back as review. Two guards:

- Every post carries `MARKER`, and `events.review_lines` drops marked
  comments, so the next rework does not read the pipeline's replies as the
  reviewer's words.
- The poller keys "a new comment" on ids, and a reply creates a review of its
  own with an empty body — nothing to mark. So the ids of everything posted
  are recorded in `OWN_POSTS`, and the poller skips them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from agent_build_kit import forges
from agent_build_kit.forges import Forge, RepoId

MARKER = "<!-- spec-driven:reply -->"

# The pipeline's own posts, per PR: {"<owner>/<repo>#<n>": [node ids]}.
# Machine-local, like the poller's own state.
OWN_POSTS = "own-posts.json"


class Reply(BaseModel):
    comment_id: str
    body: str

    @field_validator("comment_id", mode="before")
    @classmethod
    def _as_text(cls, value: object) -> str:
        """The agent echoes back the id the review prompt showed it, and what
        that looks like is the forge's business - GitHub's are numbers."""
        return str(value)


class Answer(BaseModel):
    """What the rework agent says it did, as the rework prompt asks for it.

    Strict about extra keys, because the parser tries every `{` from the end:
    the last one is usually a single reply inside the list, which would
    otherwise validate as an answer with nothing in it.
    """

    model_config = ConfigDict(extra="forbid")

    replies: list[Reply] = []
    summary: str = ""


def last_json(text: str, keys: set[str]) -> dict | None:
    """The last JSON object in an agent's final message that has any of `keys`.

    The last, not the first: an agent may quote JSON while working and put its
    answer at the end, where the prompts ask for it. And keyed, because trying
    every `{` from the end finds nested objects first — a single reply inside
    the list would otherwise pass for the whole answer.
    """
    decoder = json.JSONDecoder()
    starts = [i for i, char in enumerate(text) if char == "{"]
    for start in reversed(starts):
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(value, dict) and value.keys() & keys:
            return value
    return None


def parse_answer(text: str) -> Answer | None:
    """A rework's replies, from the end of its final message, or None."""
    value = last_json(text, {"replies", "summary"})
    if value is None:
        return None
    try:
        return Answer.model_validate(value)
    except ValidationError:
        return None


def own_posts(root: Path, slug: str, pr: int) -> set[str]:
    try:
        recorded = json.loads((root / OWN_POSTS).read_text())
    except (OSError, ValueError):
        return set()
    return set(recorded.get(f"{slug}#{pr}", []))


def record_posts(root: Path, slug: str, pr: int, ids: list[str]) -> None:
    path = root / OWN_POSTS
    try:
        recorded = json.loads(path.read_text())
    except (OSError, ValueError):
        recorded = {}
    key = f"{slug}#{pr}"
    recorded[key] = sorted({*recorded.get(key, []), *ids})
    path.write_text(json.dumps(recorded, indent=2) + "\n")


def _signed(body: str, sha: str) -> str:
    return f"{body.strip()}\n\n<sub>spec-driven rework, in {sha[:9]}</sub>\n{MARKER}"


def build_post_replies(
    *,
    root: Path,
    for_repo: Callable[[str], tuple[Forge, RepoId]] | None = None,
    log: Callable[[str], None] = print,
) -> Callable[..., None]:
    """Post a rework's answer to its PR, recording what was posted."""
    for_repo = for_repo or forges.for_repo

    def post_replies(*, repo: str, pr: int, answer_text: str, sha: str) -> None:
        answer = parse_answer(answer_text)
        if answer is None:
            log("no replies posted: the rework did not end with its answer as JSON")
            return

        forge, repo_id = for_repo(repo)
        posted: list[str] = []
        try:
            _post_all(forge, repo_id, answer, pr, sha, posted)
        finally:
            # Whatever did go out is recorded even if a later post raised:
            # an unrecorded reply is one the poller would read as review.
            record_posts(root, forges.key(repo_id), pr, [p for p in posted if p])
        log(
            f"posted {len(answer.replies)} repl(ies)"
            + (" and a summary" if answer.summary.strip() else "")
        )

    def _post_all(
        forge: Forge,
        repo_id: RepoId,
        answer: Answer,
        pr: int,
        sha: str,
        posted: list[str],
    ) -> None:
        for reply in answer.replies:
            try:
                posted += forge.post_reply(
                    repo_id, pr, note_id=reply.comment_id, body=_signed(reply.body, sha)
                )
            except Exception as error:  # noqa: BLE001 - one bad id must not cost the rest
                log(f"reply to comment {reply.comment_id} not posted: {error}")

        if answer.summary.strip():
            try:
                posted += forge.post_comment(repo_id, pr, body=_signed(answer.summary, sha))
            except Exception as error:  # noqa: BLE001
                log(f"summary comment not posted: {error}")

    return post_replies
