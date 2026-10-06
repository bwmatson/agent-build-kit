"""GitHub, over its REST and GraphQL APIs.

One client per repo owner, built with that owner's credential
(`transport.credential_for`), so units for different owners run side by side
and no account is ever switched. Nothing here starts a process: the host's
answers are parsed into the typed documents of `github_models`, and a refusal
is a `TransportError` carrying what the host said.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from agent_build_kit.forges.base import (
    BaseMissing,
    Label,
    PullRequest,
    RepoId,
    ReviewNote,
    Run,
    Stack,
    StackRefused,
    key,
)
from agent_build_kit.forges.github_models import (
    CheckNode,
    ChecksPull,
    FileDoc,
    InlineCommentDoc,
    JobsDoc,
    LabelDoc,
    NodeIdDoc,
    NumberDoc,
    PullConnection,
    PullDoc,
    PullNode,
    ReviewDoc,
    StackDoc,
)
from agent_build_kit.forges.transport import (
    PAGE_EXCERPT,
    AuthError,
    NotFound,
    Response,
    Transport,
    TransportError,
    credential_for,
)
from agent_build_kit.pipeline import units
from agent_build_kit.settings import settings

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

log = logging.getLogger(__name__)

_HOST = "https://api.github.com"
# The most the list endpoints give a page of.
_PAGE = 100
# What creating a pull request says, in the older wording, when the base branch
# is not on the host. The current one is an error on the `base` field.
_BASE_MISSING = ("Base ref must be a branch", "Base sha can't be blank")

# The checks of one pull request's newest commit. A commit status comes through
# the same rollup as a check run, and is told apart by what it lacks.
_CHECKS = """
commits(last: 1) { nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
  __typename
  ... on CheckRun { name conclusion detailsUrl }
} } } } } }
"""

# What a PullRequest is made of. `comments` alone misses a normal review
# entirely: it holds issue-level comments only, so a reviewer who leaves inline
# notes and submits CHANGES_REQUESTED registers as silence - hence `reviews` and
# `reviewDecision`.
_LISTING = (
    """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number headRefName baseRefName state isDraft mergedAt mergeable reviewDecision
        labels(first: 100) { nodes { name } }
        comments(first: 100) { nodes { id body } }
        reviews(first: 100) { nodes { id state } }
"""
    + _CHECKS
    + """
      }
    }
  }
}
"""
)
_CHECKS_OF_ONE = (
    """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
"""
    + _CHECKS
    + """
    }
  }
}
"""
)
_DRAFT = {True: "convertPullRequestToDraft", False: "markPullRequestReadyForReview"}

_FAILING = ("FAILURE", "TIMED_OUT")
_CANCELLED = ("CANCELLED",)
_MERGEABLE = {"MERGEABLE": True, "CONFLICTING": False}
# A failed Actions run, named in a check's link.
_RUN_URL = re.compile(r"/actions/runs/(?P<run>\d+)")
_LOG_CHARS = 6000
# A job log's lines: a byte order mark, a timestamp and nothing else.
_JOB_LINE = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_ERROR_LINE = "##[error]"
_FAILED_JOB = ("failure", "timed_out")

# `git@github.com:owner/name.git`, `https://github.com/owner/name`,
# `ssh://git@github.com/owner/name.git`, `alias:owner/name.git` (an ssh host
# alias carrying a deploy key). The last form is why this pattern matches any
# host and must be tried after the host-anchored ones.
_ORIGIN = re.compile(
    r"^(?:[\w.@-]+:(?!//)|[a-z+]+://[^/]+/)(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"
)


class GitHubForge:
    name: str = "github"
    implemented: bool = True
    # Only the agent's own reads, and the login a credential may come from, need
    # `gh`; no operation of this forge runs it.
    client: str | None = "gh"
    # GitHub deletes the head branch on merge, so only the local one is ours.
    deletes_head_branch_on_merge: bool = True
    supports_stacks: bool = True
    # Annotated, not inferred: the Protocol's attribute is read-write, so a
    # narrower literal type would not satisfy it.
    denied_commands: tuple[tuple[str, ...], ...] = (("gh", "pr", "merge"),)
    read_commands: tuple[tuple[str, ...], ...] = (("gh", "pr", "view"), ("gh", "pr", "diff"))
    requires: tuple[str, ...] = ("slug",)
    ci_name: str = "GitHub Actions"

    def __init__(self, http: httpx.BaseTransport | None = None) -> None:
        # The transport every API call goes through; None is the network.
        self.http = http
        self._transports: dict[str, Transport] = {}
        self._lock = threading.Lock()

    def parse_remote(self, url: str) -> RepoId | None:
        match = _ORIGIN.match(url.strip())
        if not match:
            return None
        return RepoId(forge=self.name, account=match["owner"], name=match["name"])

    def identity(self, repo: RepoConfig) -> RepoId:
        """The repo's GitHub identity from abk.yaml: `owner/name`."""
        account, _, name = repo.slug.partition("/")
        return RepoId(forge=self.name, account=account, name=name)

    def config_entry(self, repo: RepoId) -> dict[str, object]:
        return {"slug": key(repo)}

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str:
        base = f"https://github.com/{repo.account}/{repo.name}"
        return f"{base}/pull/{pr}" if pr else base

    # --- the wire -------------------------------------------------------------------

    def _transport(self, account: str, run: Run | None = None) -> Transport:
        """The connection for one owner, rebuilt when its credential is read again."""
        credentials = credential_for(self.name, account, run=run)
        with self._lock:
            held = self._transports.get(account)
            if held is None or held.credentials is not credentials:
                held = Transport(_HOST, credentials, transport=self.http)
                self._transports[account] = held
            return held

    def _call(
        self,
        repo: RepoId,
        method: str,
        path: str = "",
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        run: Run | None = None,
    ) -> Response:
        """One REST call, `path` being under the repository's own resource."""
        return self._transport(repo.account, run).request(
            method, f"/repos/{key(repo)}{path}", json=json, params=params
        )

    def _pages[Doc: BaseModel](
        self, repo: RepoId, path: str, model: type[Doc], params: dict[str, str] | None = None
    ) -> list[Doc]:
        """Every page of a list, following the host's `next` link."""
        found: list[Doc] = []
        page = 1
        while True:
            reply = self._call(
                repo,
                "GET",
                path,
                params={**(params or {}), "per_page": str(_PAGE), "page": str(page)},
            )
            found += _items(reply, model, f"GET {path}")
            if 'rel="next"' not in reply.headers.get("link", ""):
                return found
            page += 1

    def _graphql(self, repo: RepoId, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """One GraphQL call. Its failures come back with a 200, in `errors`.

        A query and the draft mutations are both safe to repeat, so a failed
        attempt is retried like a read."""
        reply = self._transport(repo.account).request(
            "POST", "/graphql", json={"query": query, "variables": variables}, idempotent=True
        )
        data = reply.data if isinstance(reply.data, dict) else {}
        found = data.get("data")
        errors = data.get("errors")
        if errors or not isinstance(found, dict):
            said = "; ".join(str(e.get("message", "")) for e in errors or [] if isinstance(e, dict))
            raise TransportError(f"POST graphql: {said or _unexpected('graphql', reply)}")
        return found

    # --- access ---------------------------------------------------------------------

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        """Whether a credential is held for this repo's owner.

        The owner decides which account's token is used, and a call against
        another account's private repo reports it as nonexistent rather than
        forbidden - indistinguishable from a repo with no PRs.
        """
        try:
            credential_for(self.name, repo.account, run=run)
        except AuthError as error:
            return str(error)
        return ""

    def access_fix(self, repo: RepoId) -> str:
        return f"gh auth login (as {repo.account})"

    def merge_guard(self, repo: RepoId, *, branch: str, run: Run | None = None) -> str:
        """What stops a merge on the server, or "" when nothing does.

        Branch protection is absent on a free private repo, where the answer
        is honestly "nothing" - which is worth saying out loud, because the
        policy hook is then the only thing between an agent and its own merge.
        """
        try:
            found = self._call(
                repo, "GET", f"/branches/{quote(branch, safe='/')}/protection", run=run
            )
        except (NotFound, AuthError):
            # 404 where there is none, 403 where the plan has no such thing.
            return f"no branch protection on {branch}"
        except TransportError as error:
            return f"cannot tell what guards {branch}: {error}"
        return "" if found.data else f"no branch protection on {branch}"

    # --- pull requests --------------------------------------------------------------

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        # The owner qualifies the branch, as the API asks: a bare name matches
        # nothing on a fork's or another owner's.
        try:
            found = self._call(
                repo,
                "GET",
                "/pulls",
                params={"head": f"{repo.account}:{head}", "state": "all", "per_page": "1"},
            )
            return _items(found, NumberDoc, "GET pulls")[0].number
        except (TransportError, IndexError):
            # Could not tell reads as no pull request yet.
            return None

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        try:
            made = self._call(
                repo,
                "POST",
                "/pulls",
                json={"head": head, "base": base, "title": title, "body": body},
            )
        except TransportError as error:
            # The host's words only: the request holds the title and body.
            if error.status == 422 and _base_missing(error):
                raise BaseMissing(_reason(error)) from error
            if error.status == 422:
                raise TransportError(f"POST pulls: {_reason(error)}") from error
            raise
        return _parse(made, NumberDoc, "POST pulls").number

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None:
        """Change a PR's base or body, never raising.

        GitHub often retargets a PR on its own when its base branch is deleted
        on merge, but not always, and one left pointing at a deleted branch
        shows a diff containing everything. Doing it explicitly is harmless
        when GitHub already has - and not worth failing a restack over when it
        does not work.
        """
        changes = {**({"base": base} if base else {}), **({"body": body} if body else {})}
        if not changes:
            return
        try:
            self._call(repo, "PATCH", f"/pulls/{pr}", json=changes)
        except TransportError as error:
            log.warning("could not update pull request %s of %s: %s", pr, key(repo), error)

    # --- stacks ---------------------------------------------------------------------

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        found = self._stacks(repo, "GET", params={"pull_request": str(pr)})
        stacks = [_stack(item) for item in found] if isinstance(found, list) else []
        return next((stack for stack in stacks if pr in stack.pulls), None)

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack:
        # Bottom first: GitHub checks each pull request's base against the head
        # of the one before it.
        return _stack(self._stacks(repo, "POST", json={"pull_requests": list(pulls)}))

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack:
        found = self._stacks(repo, "POST", f"/{stack}/add", json={"pull_requests": list(pulls)})
        return _stack(found)

    def _stacks(self, repo: RepoId, method: str, path: str = "", **kwargs: Any) -> object:
        """One call to the pull request stacks API, or StackRefused saying why not."""
        try:
            return self._call(repo, method, f"/stacks{path}", **kwargs).data
        except TransportError as error:
            # 409: another request is changing the same stack right now.
            raise StackRefused(_reason(error), concurrent=error.status == 409) from error

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str, head: str = ""
    ) -> None:
        """Publish a result as a commit status on the tested SHA.

        Called after the push: GitHub rejects a status for a commit it has not
        seen. 139 characters is GitHub's own limit for the description.
        """
        payload = {
            "state": "success" if ok else "failure",
            "context": context,
            "description": description[:139],
        }
        try:
            self._call(repo, "POST", f"/statuses/{quote(sha)}", json=payload)
        except TransportError as error:
            log.warning("could not post %s on %s of %s: %s", context, sha, key(repo), error)

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        """Every pull request of the repo, one query to a page."""
        nodes: list[PullNode] = []
        cursor: str | None = None
        while True:
            data = self._graphql(
                repo, _LISTING, {"owner": repo.account, "name": repo.name, "cursor": cursor}
            )
            listed = (data.get("repository") or {}).get("pullRequests")
            if listed is None:
                raise TransportError(f"POST graphql: no repository {key(repo)} in the answer")
            page = _model(PullConnection, listed, "pull requests")
            nodes += page.nodes
            if not page.page_info.has_next_page or not page.page_info.end_cursor:
                break
            cursor = page.page_info.end_cursor
        pulls = [_view(node) for node in nodes]
        return [p for p in pulls if p.head.startswith(head_prefix)] if head_prefix else pulls

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        return [item.filename for item in self._pages(repo, f"/pulls/{pr}/files", FileDoc)]

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        """The reviewer's words: review bodies, then inline comments.

        Two requests, made only when a rework is already being dispatched;
        adding them to the poll would cost one per open PR per tick. An inline
        comment whose code has changed comes back with `line: null`, which is
        what `live` records - after a rework that is precisely the comment the
        rework addressed.
        """
        notes = [
            ReviewNote(id=str(review.id), body=review.body or "", live=False)
            for review in self._pages(repo, f"/pulls/{pr}/reviews", ReviewDoc)
        ]
        notes += [
            ReviewNote(
                id=str(comment.id),
                body=comment.body or "",
                path=comment.path,
                line=comment.line,
                live=comment.line is not None,
            )
            for comment in self._pages(repo, f"/pulls/{pr}/comments", InlineCommentDoc)
        ]
        return notes

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        """Answer one review comment, and report what the poller will see.

        A reply creates a review of its own with an empty body, which the
        poller would otherwise read as new feedback - so both ids come back to
        be recorded as the pipeline's own.
        """
        route = f"/pulls/{pr}/comments/{note_id}/replies"
        try:
            made = _parse(
                self._call(repo, "POST", route, json={"body": body}), InlineCommentDoc, "POST reply"
            )
        except TransportError as error:
            log.warning("could not reply to %s on %s of %s: %s", note_id, pr, key(repo), error)
            return []
        ids = [made.node_id]
        if made.pull_request_review_id is not None:
            route = f"/pulls/{pr}/reviews/{made.pull_request_review_id}"
            try:
                ids.append(
                    _parse(self._call(repo, "GET", route), NodeIdDoc, f"GET {route}").node_id
                )
            except TransportError as error:
                log.warning("could not read the review a reply to %s made: %s", note_id, error)
        return [i for i in ids if i]

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        try:
            made = _parse(
                self._call(repo, "POST", f"/issues/{pr}/comments", json={"body": body}),
                NodeIdDoc,
                "POST comment",
            )
        except TransportError as error:
            log.warning("could not comment on %s of %s: %s", pr, key(repo), error)
            return []
        return [made.node_id] if made.node_id else []

    # --- checks ---------------------------------------------------------------------

    def _runs_with(
        self, repo: RepoId, pr: int, conclusions: Collection[str]
    ) -> tuple[list[CheckNode], list[str]]:
        """The checks of a pull request that ended as one of `conclusions`, and
        the workflow runs they belong to."""
        data = self._graphql(
            repo, _CHECKS_OF_ONE, {"owner": repo.account, "name": repo.name, "number": pr}
        )
        found = (data.get("repository") or {}).get("pullRequest")
        if found is None:
            raise TransportError(f"POST graphql: no pull request {pr} in {key(repo)}")
        checks = _rollup(_model(ChecksPull, found, "pull request checks").commits)
        ended = [c for c in checks if (c.conclusion or "").upper() in conclusions]
        runs = sorted({m["run"] for c in ended if (m := _RUN_URL.search(c.details_url or ""))})
        return ended, runs

    def rerun_checks(self, repo: RepoId, pull: PullRequest) -> None:
        """Re-run the workflow runs behind the cancelled checks, their cancelled
        jobs included."""
        _, runs = self._runs_with(repo, pull.number, _CANCELLED)
        for run in runs:
            try:
                self._call(repo, "POST", f"/actions/runs/{run}/rerun-failed-jobs")
            except TransportError as error:
                raise TransportError(
                    f"rerun of run {run} ({key(repo)}): {_reason(error)}"
                ) from error

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        """The failed CI jobs' logs, for the rework that fixes them.

        "failing checks: <name>" is not enough when the failure is a test tier
        1 never ran, and nothing local can say why.
        """
        if not pull.failing_checks:
            return ""
        failed, runs = self._runs_with(repo, pull.number, _FAILING)
        names = ", ".join(str(c.name) for c in failed)
        parts = []
        for run in runs:
            # A run still in progress has no log as a whole, though a job that
            # has finished does: the check fails in a minute and the slowest
            # job takes several, and the poller reports the failure at once.
            text = self._failed_job_logs(repo, run)
            if not text.strip():
                parts.append(
                    f"CI run {run} ({names}) failed, but its log could not be fetched "
                    "(the run may still be in progress)."
                )
                continue
            parts.append(f"CI run {run} ({names}), end of its failed log:\n```\n{text}\n```")
        return "\n\n".join(parts)

    def _failed_job_logs(self, repo: RepoId, run: str) -> str:
        """The log of each failed job of `run`, up to where the job reported its error.

        A job's whole log ends in the runner's clean-up, so the tail of it says
        nothing; the failure is in the lines before the last `##[error]`.
        """
        route = f"/actions/runs/{run}/jobs"
        try:
            jobs = _parse(
                self._call(repo, "GET", route, params={"per_page": str(_PAGE)}),
                JobsDoc,
                f"GET {route}",
            ).jobs
        except TransportError:
            return ""
        out = []
        for job in jobs:
            if (job.conclusion or "") not in _FAILED_JOB:
                continue
            lines = [_JOB_LINE.sub("", line) for line in self._job_log(repo, job.id).splitlines()]
            errors = [i for i, line in enumerate(lines) if _ERROR_LINE in line]
            if errors:
                lines = lines[: errors[-1] + 1]
            text = "\n".join(lines).strip()
            if text:
                out.append(f"{job.name}:\n{text[-_LOG_CHARS:]}")
        return "\n\n".join(out)

    def _job_log(self, repo: RepoId, job: int) -> str:
        """A job's log, or "" when it cannot be had.

        The host answers with a redirect to the storage the log lives in. That
        is fetched without our credential: it is another host's, and the link
        is signed.
        """
        try:
            reply = self._call(repo, "GET", f"/actions/jobs/{job}/logs")
            location = reply.headers.get("location")
            if not location:
                return reply.text
            with httpx.Client(
                transport=self.http, timeout=settings.forge_timeout_seconds
            ) as storage:
                stored = storage.get(location)
            return stored.text if stored.is_success else ""
        except (TransportError, httpx.HTTPError):
            return ""

    # --- labels ---------------------------------------------------------------------

    def _ensure_label(self, repo: RepoId, label: Label) -> None:
        """Make the repo's label what `label` says: created when missing, and
        recoloured or re-described when the repo's copy has drifted, so a
        change to the vocabulary reaches a repo that already has the label."""
        # The host matches names without regard to case, so `Running` already
        # there means creating `running` would fail every time.
        wanted = label.name.casefold()
        for item in self._pages(repo, "/labels", LabelDoc):
            if item.name.casefold() != wanted:
                continue
            same_colour = item.color.casefold() == label.color.casefold()
            if not same_colour or (item.description or "") != label.description:
                self._call(
                    repo,
                    "PATCH",
                    f"/labels/{quote(item.name, safe='')}",
                    json={"color": label.color, "description": label.description},
                )
            return
        self._call(
            repo,
            "POST",
            "/labels",
            json={"name": label.name, "color": label.color, "description": label.description},
        )

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        self._ensure_label(repo, label)
        self._call(repo, "POST", f"/issues/{pr}/labels", json={"labels": [label.name]})

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        self._ensure_label(repo, label)
        present = {item.name for item in self._pages(repo, f"/issues/{pr}/labels", LabelDoc)}
        self._call(repo, "POST", f"/issues/{pr}/labels", json={"labels": [label.name]})
        for name in sorted((present & set(family)) - {label.name}):
            self.remove_label(repo, pr, name)

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        """Take a label off by name. One that is not on the pull request returns
        normally; any other refusal raises."""
        try:
            self._call(repo, "DELETE", f"/issues/{pr}/labels/{quote(name, safe='')}")
        except NotFound:
            pass

    # --- state ----------------------------------------------------------------------

    def set_draft(self, repo: RepoId, pr: int, draft: bool) -> None:
        """Make a pull request a draft or publish it, writing only on a change.

        A refusal raises with the host's message.
        """
        route = f"/pulls/{pr}"
        current = _parse(self._call(repo, "GET", route), PullDoc, f"GET {route}")
        if current.draft == draft:
            return
        mutation = _DRAFT[draft]
        self._graphql(
            repo,
            f"mutation($id: ID!) {{ {mutation}(input: {{pullRequestId: $id}}) "
            "{ pullRequest { id isDraft } } }",
            {"id": current.node_id},
        )

    def close_pr(self, repo: RepoId, pr: int) -> None:
        """Close without merging - a satisfied unit's stale pull request.

        A refusal raises, unlike `update_pr`: a close that did not happen must
        not read as one that did.
        """
        self._call(repo, "PATCH", f"/pulls/{pr}", json={"state": "closed"})

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        """Not reached in practice: GitHub deletes the head branch on merge,
        so `deletes_head_branch_on_merge` keeps callers away from this."""
        try:
            self._call(repo, "DELETE", f"/git/refs/heads/{quote(branch, safe='/')}")
        except TransportError as error:
            log.warning("could not delete %s of %s: %s", branch, key(repo), error)


FORGE = GitHubForge()


def _unexpected(endpoint: str, response: Response) -> str:
    return f"{endpoint}: not the document expected: {response.text[:PAGE_EXCERPT]}"


def _model[Doc: BaseModel](model: type[Doc], found: object, what: str) -> Doc:
    try:
        return model.model_validate(found)
    except ValidationError as error:
        excerpt = str(found)[:PAGE_EXCERPT]
        raise TransportError(f"{what}: not the document expected: {excerpt}") from error


def _parse[Doc: BaseModel](response: Response, model: type[Doc], endpoint: str) -> Doc:
    try:
        return model.model_validate(response.data)
    except ValidationError as error:
        raise TransportError(_unexpected(endpoint, response)) from error


def _items[Doc: BaseModel](response: Response, model: type[Doc], endpoint: str) -> list[Doc]:
    if not isinstance(response.data, list):
        raise TransportError(_unexpected(endpoint, response))
    try:
        return [model.model_validate(item) for item in response.data]
    except ValidationError as error:
        raise TransportError(_unexpected(endpoint, response)) from error


def _said(error: TransportError) -> tuple[str, list[dict]]:
    """What the host said in a refusal: its message, and its `errors` entries."""
    try:
        body = json.loads(error.body or "{}")
    except ValueError:
        return "", []
    if not isinstance(body, dict):
        return "", []
    errors = [e for e in body.get("errors") or [] if isinstance(e, dict)]
    return str(body.get("message") or ""), errors


def _reason(error: TransportError) -> str:
    """A refusal in the host's words: the status, its message and the messages of
    its `errors`; the transport's own text when it was no refusal."""
    if error.status is None:
        return str(error)
    message, errors = _said(error)
    details = [str(e.get("message", "")) for e in errors]
    said = "; ".join(part for part in [message, *details] if part)
    return f"HTTP {error.status}: {said or error}"


def _base_missing(error: TransportError) -> bool:
    """Whether a 422 says the base branch is not on the host: an error on the
    `base` field, or the older wording. Only what the host said counts."""
    message, errors = _said(error)
    words = " ".join([message, *(str(e.get("message", "")) for e in errors)])
    return any(e.get("field") == "base" for e in errors) or any(t in words for t in _BASE_MISSING)


def _stack(found: object) -> Stack:
    # Any answer not shaped like a stack is a refusal, not a crash: the step
    # that asks has already opened the pull request, and must not fail it.
    try:
        doc = StackDoc.model_validate(found)
    except ValidationError as error:
        raise StackRefused(f"unexpected answer from the stacks API: {found!r:.200}") from error
    return Stack(
        number=doc.number,
        open=doc.open,
        pulls=tuple(pull.number for pull in doc.pull_requests or []),
    )


def _rollup(commits: Any) -> list[CheckNode]:
    """The check runs on a pull request's newest commit. A commit status is in
    the rollup too, and is not a check."""
    return [
        check
        for edge in (commits.nodes if commits else [])
        if (rollup := edge.commit.status_check_rollup) and rollup.contexts
        for check in rollup.contexts.nodes
        if check.typename == "CheckRun"
    ]


def _named(checks: list[CheckNode], conclusions: Collection[str]) -> tuple[str, ...]:
    return tuple(sorted(str(c.name) for c in checks if (c.conclusion or "").upper() in conclusions))


def _view(pull: PullNode) -> PullRequest:
    checks = _rollup(pull.commits)
    return PullRequest(
        number=pull.number,
        head=pull.head_ref_name,
        base=pull.base_ref_name,
        state=(
            units.MERGED if pull.merged_at else units.CLOSED if pull.state == "CLOSED" else "open"
        ),
        draft=pull.is_draft,
        labels=tuple(sorted(label.name for label in pull.labels.nodes)) if pull.labels else (),
        conversation=tuple(_conversation(pull)),
        comment_bodies=tuple(c.body or "" for c in pull.comments.nodes) if pull.comments else (),
        review_decision="changes_requested" if pull.review_decision == "CHANGES_REQUESTED" else "",
        failing_checks=_named(checks, _FAILING),
        cancelled_checks=_named(checks, _CANCELLED),
        # UNKNOWN is what GitHub says until it has worked the answer out.
        mergeable=_MERGEABLE.get(pull.mergeable or ""),
    )


def _conversation(pull: PullNode) -> list[str]:
    """Every comment and submitted review on the PR, by id.

    Not a PENDING review: that is a draft the reviewer has not submitted.
    GitHub shows it to its own author, and the repo is read as its owner - so a
    review still being written would count as new and send the unit back for
    rework with nothing to act on.
    """
    ids = [c.id for c in pull.comments.nodes if c.id] if pull.comments else []
    if pull.reviews:
        ids += [r.id for r in pull.reviews.nodes if r.id and r.state != "PENDING"]
    return ids
