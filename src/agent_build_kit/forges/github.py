"""GitHub, over its REST and GraphQL APIs.

One `githubkit` client per repo owner, built with that owner's credential
(`transport.credential_for`), so units for different owners run side by side
and no account is ever switched. Nothing here starts a process: calls go
through githubkit's typed REST methods and its GraphQL call, the host's
answers are parsed into the documents of `github_models`, and a refusal is a
`TransportError` carrying what the host said.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import httpx
from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import (
    GitHubException,
    GraphQLFailed,
    RateLimitExceeded,
    RequestError,
    RequestFailed,
)
from githubkit.response import Response
from pydantic import BaseModel, ValidationError

from agent_build_kit.forges.base import (
    BaseMissing,
    FileChange,
    Label,
    PullRequest,
    RepoId,
    ReviewNote,
    Run,
    Stack,
    StackRefused,
    fit_description,
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
    TRANSIENT,
    AuthError,
    Credentials,
    HostError,
    NotFound,
    RateLimited,
    TransportError,
    credential_for,
)
from agent_build_kit.pipeline import units
from agent_build_kit.settings import settings

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

log = logging.getLogger(__name__)

# The most the list endpoints give a page of.
_PAGE = 100
# What creating a pull request says, in the older wording, when the base branch
# is not on the host. The current one is an error on the `base` field.
_BASE_MISSING = ("Base ref must be a branch", "Base sha can't be blank")
# What removing a label that is not on the pull request says.
_NO_SUCH_LABEL = "Label does not exist"
# Calls that are safe to make again after a failed attempt.

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
_JOB_LINE = re.compile(r"^\N{BYTE ORDER MARK}?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
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
    description_limit: int = 65_536

    def __init__(self, http: httpx.BaseTransport | None = None) -> None:
        # The transport every API call goes through; None is the network.
        self.http = http
        self._clients: dict[str, tuple[Credentials, GitHub[Any]]] = {}
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

    def _client(self, account: str, credentials: Credentials) -> GitHub[Any]:
        """The client for one owner, rebuilt when its credential is read again.

        Caching is off, so a read is never answered from an earlier one; a
        redirect is not followed, so a job log's signed link is read by us and
        fetched without the credential."""
        with self._lock:
            held = self._clients.get(account)
            if held is None or held[0] is not credentials:
                client = GitHub(
                    TokenAuthStrategy(credentials.token),
                    base_url=settings.github_api_url.rstrip("/"),
                    timeout=settings.forge_timeout_seconds,
                    transport=self.http,
                    auto_retry=False,
                    http_cache=False,
                    follow_redirects=False,
                )
                held = (credentials, client)
                self._clients[account] = held
            return held[1]

    @contextmanager
    def _on(self, repo: RepoId, run: Run | None = None) -> Iterator[GitHub[Any]]:
        """The repo owner's client, for calls whose failures leave as the
        transport's errors."""
        credentials = credential_for(self.name, repo.account, run=run)
        try:
            yield self._client(repo.account, credentials)
        except GitHubException as error:
            raise _refusal(error, credentials) from error
        except ValidationError as error:
            raise TransportError(
                f"not the document expected: {str(error)[:PAGE_EXCERPT]}"
            ) from error

    def _pages[Doc: BaseModel](
        self,
        repo: RepoId,
        select: Callable[[GitHub[Any]], Callable[..., Response[Any, Any]]],
        model: type[Doc],
        **params: Any,
    ) -> list[Doc]:
        """Every page of a list, following the host's `next` link."""
        found: list[Doc] = []
        page = 1
        while True:
            with self._on(repo) as gh:
                endpoint = select(gh)
                reply = endpoint(repo.account, repo.name, **params, per_page=_PAGE, page=page)
            found += _items(reply, model, endpoint.__name__)
            if 'rel="next"' not in reply.headers.get("link", ""):
                return found
            page += 1

    def _graphql(self, repo: RepoId, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """One GraphQL call. Its failures come back with a 200, in `errors`.

        A query and the draft mutations are both safe to repeat, so a failed
        attempt is retried like a read."""
        with self._on(repo) as gh:
            return gh.graphql(query, variables)

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
            with self._on(repo, run) as gh:
                found = gh.rest.repos.get_branch_protection(repo.account, repo.name, branch)
        except (NotFound, AuthError):
            # 404 where there is none, 403 where the plan has no such thing.
            return f"no branch protection on {branch}"
        except TRANSIENT:
            raise
        except TransportError as error:
            return f"cannot tell what guards {branch}: {error}"
        return "" if _body(found) else f"no branch protection on {branch}"

    # --- pull requests --------------------------------------------------------------

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        # The owner qualifies the branch, as the API asks: a bare name matches
        # nothing on a fork's or another owner's.
        # An answer that cannot be read raises: only an empty list is "none".
        with self._on(repo) as gh:
            found = gh.rest.pulls.list(
                repo.account, repo.name, head=f"{repo.account}:{head}", state="all", per_page=1
            )
        pulls = _items(found, NumberDoc, "GET pulls")
        return pulls[0].number if pulls else None

    def comment_exists(
        self, repo: RepoId, pr: int, marker: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        if reply_to is None:
            comments = self._pages(
                repo, lambda gh: gh.rest.issues.list_comments, InlineCommentDoc, issue_number=pr
            )
        else:
            comments = [
                comment
                for comment in self._pages(
                    repo,
                    lambda gh: gh.rest.pulls.list_review_comments,
                    InlineCommentDoc,
                    pull_number=pr,
                )
                if comment.in_reply_to_id == int(reply_to)
            ]
        return next(
            (c.node_id for c in comments if c.body == body and marker in body and c.node_id), None
        )

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        try:
            with self._on(repo) as gh:
                made = gh.rest.pulls.create(
                    repo.account,
                    repo.name,
                    data={
                        "head": head,
                        "base": base,
                        "title": title,
                        "body": fit_description(body, self.description_limit),
                    },
                )
        except TransportError as error:
            # The host's words only: the request holds the title and body.
            if error.status == 422 and _base_missing(error):
                raise BaseMissing(_reason(error)) from error
            if error.status == 422 and _already_exists(error):
                existing = self.find_pr(repo, head=head)
                if existing is not None:
                    return existing
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
        changes: dict[str, Any] = {
            **({"base": base} if base else {}),
            **({"body": fit_description(body, self.description_limit)} if body else {}),
        }
        if not changes:
            return
        try:
            with self._on(repo) as gh:
                gh.rest.pulls.update(repo.account, repo.name, pr, **changes)
        except TRANSIENT:
            raise
        except TransportError as error:
            log.warning("could not update pull request %s of %s: %s", pr, key(repo), error)

    # --- stacks ---------------------------------------------------------------------

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        found = self._stacks(repo, "GET", params={"pull_request": pr})
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
        """One call to the pull request stacks API, which githubkit has no typed
        method for, or StackRefused saying why not."""
        try:
            with self._on(repo) as gh:
                return _body(gh.request(method, f"/repos/{key(repo)}/stacks{path}", **kwargs))
        except TRANSIENT:
            raise
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
        try:
            with self._on(repo) as gh:
                gh.rest.repos.create_commit_status(
                    repo.account,
                    repo.name,
                    sha,
                    state="success" if ok else "failure",
                    context=context,
                    description=description[:139],
                )
        except TRANSIENT:
            raise
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
        files = self._pages(repo, lambda gh: gh.rest.pulls.list_files, FileDoc, pull_number=pr)
        return [item.filename for item in files]

    def pr_changes(self, repo: RepoId, pr: int) -> list[FileChange]:
        files = self._pages(repo, lambda gh: gh.rest.pulls.list_files, FileDoc, pull_number=pr)
        return [
            FileChange(path=item.filename, additions=item.additions, deletions=item.deletions)
            for item in files
        ]

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
            for review in self._pages(
                repo, lambda gh: gh.rest.pulls.list_reviews, ReviewDoc, pull_number=pr
            )
        ]
        notes += [
            ReviewNote(
                id=str(comment.id),
                body=comment.body or "",
                path=comment.path,
                line=comment.line,
                live=comment.line is not None,
            )
            for comment in self._pages(
                repo,
                lambda gh: gh.rest.pulls.list_review_comments,
                InlineCommentDoc,
                pull_number=pr,
            )
        ]
        return notes

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        """Answer one review comment, and report what the poller will see.

        A reply creates a review of its own with an empty body, which the
        poller would otherwise read as new feedback - so both ids come back to
        be recorded as the pipeline's own.
        """
        try:
            with self._on(repo) as gh:
                reply = gh.rest.pulls.create_reply_for_review_comment(
                    repo.account, repo.name, pr, int(note_id), data={"body": body}
                )
            made = _parse(reply, InlineCommentDoc, "POST reply")
        except TRANSIENT:
            raise
        except (TransportError, ValueError) as error:
            log.warning("could not reply to %s on %s of %s: %s", note_id, pr, key(repo), error)
            return []
        ids = [made.node_id]
        if made.pull_request_review_id is not None:
            try:
                with self._on(repo) as gh:
                    review = gh.rest.pulls.get_review(
                        repo.account, repo.name, pr, made.pull_request_review_id
                    )
                ids.append(_parse(review, NodeIdDoc, "GET review").node_id)
            except TRANSIENT:
                raise
            except TransportError as error:
                log.warning("could not read the review a reply to %s made: %s", note_id, error)
        return [i for i in ids if i]

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        try:
            with self._on(repo) as gh:
                reply = gh.rest.issues.create_comment(
                    repo.account, repo.name, pr, data={"body": body}
                )
            made = _parse(reply, NodeIdDoc, "POST comment")
        except TRANSIENT:
            raise
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
                with self._on(repo) as gh:
                    gh.rest.actions.re_run_workflow_failed_jobs(repo.account, repo.name, int(run))
            except TRANSIENT:
                raise
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
        try:
            with self._on(repo) as gh:
                listed = gh.rest.actions.list_jobs_for_workflow_run(
                    repo.account, repo.name, int(run), per_page=_PAGE
                )
            jobs = _parse(listed, JobsDoc, "GET jobs").jobs
        except TRANSIENT:
            raise
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
            with self._on(repo) as gh:
                reply = gh.rest.actions.download_job_logs_for_workflow_run(
                    repo.account, repo.name, job
                )
            location = reply.headers.get("location")
            if not location:
                return reply.text
            try:
                with httpx.Client(
                    transport=self.http, timeout=settings.forge_timeout_seconds
                ) as storage:
                    stored = storage.get(location)
            except httpx.TransportError as error:
                raise HostError(f"GET job log storage: {error!r}") from error
            if stored.status_code >= 500:
                raise HostError(f"GET job log storage: {stored.status_code}")
            return stored.text if stored.is_success else ""
        except TRANSIENT:
            raise
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
        for item in self._pages(repo, lambda gh: gh.rest.issues.list_labels_for_repo, LabelDoc):
            if item.name.casefold() != wanted:
                continue
            same_colour = item.color.casefold() == label.color.casefold()
            if not same_colour or (item.description or "") != label.description:
                with self._on(repo) as gh:
                    gh.rest.issues.update_label(
                        repo.account,
                        repo.name,
                        item.name,
                        data={"color": label.color, "description": label.description},
                    )
            return
        with self._on(repo) as gh:
            gh.rest.issues.create_label(
                repo.account,
                repo.name,
                data={
                    "name": label.name,
                    "color": label.color,
                    "description": label.description,
                },
            )

    def _attach(self, repo: RepoId, pr: int, name: str) -> None:
        with self._on(repo) as gh:
            gh.rest.issues.add_labels(repo.account, repo.name, pr, data={"labels": [name]})

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        self._ensure_label(repo, label)
        self._attach(repo, pr, label.name)

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        self._ensure_label(repo, label)
        on_pr = self._pages(
            repo, lambda gh: gh.rest.issues.list_labels_on_issue, LabelDoc, issue_number=pr
        )
        present = {item.name for item in on_pr}
        self._attach(repo, pr, label.name)
        for name in sorted((present & set(family)) - {label.name}):
            self.remove_label(repo, pr, name)

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        """Take a label off by name. One that is not on the pull request returns
        normally; any other refusal raises, a 404 that says something else
        (a credential that cannot see the repository) included."""
        try:
            with self._on(repo) as gh:
                gh.rest.issues.remove_label(repo.account, repo.name, pr, name)
        except NotFound as error:
            if _NO_SUCH_LABEL not in _reason(error):
                raise

    # --- state ----------------------------------------------------------------------

    def set_draft(self, repo: RepoId, pr: int, draft: bool) -> None:
        """Make a pull request a draft or publish it, writing only on a change.

        A refusal raises with the host's message.
        """
        with self._on(repo) as gh:
            reply = gh.rest.pulls.get(repo.account, repo.name, pr)
        current = _parse(reply, PullDoc, f"GET pulls/{pr}")
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
        with self._on(repo) as gh:
            gh.rest.pulls.update(repo.account, repo.name, pr, data={"state": "closed"})

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        """Not reached in practice: GitHub deletes the head branch on merge,
        so `deletes_head_branch_on_merge` keeps callers away from this."""
        try:
            with self._on(repo) as gh:
                gh.rest.git.delete_ref(repo.account, repo.name, f"heads/{branch}")
        except TRANSIENT:
            raise
        except TransportError as error:
            log.warning("could not delete %s of %s: %s", branch, key(repo), error)


FORGE = GitHubForge()


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _refusal(error: GitHubException, credentials: Credentials) -> TransportError:
    """What the host's refusal is, as the transport's errors: authentication, not
    found (naming whose credential was used), a rate limit, a host failure."""
    if isinstance(error, GraphQLFailed):
        said = "; ".join(e.message for e in error.response.errors or [])
        return TransportError(f"POST graphql: {said or 'no answer'}")
    if not isinstance(error, RequestError):
        return TransportError(f"{type(error).__name__}: {error!r}")
    if not isinstance(error, RequestFailed):
        return HostError(f"{error!r}")
    reply = error.response
    where = f"{error.request.method} {error.request.url.path}"
    who = f"with the credential for {credentials.owner} from {credentials.source}"
    status = reply.status_code
    refused: TransportError
    if isinstance(error, RateLimitExceeded):
        wait = error.retry_after.total_seconds()
        refused = RateLimited(f"{where}: rate limited", retry_after=wait)
    elif status in (401, 403):
        refused = AuthError(f"{where}: {status} {who}: {reply.text[:PAGE_EXCERPT]}")
    elif status == 404:
        refused = NotFound(
            f"{where}: not found {who}", account=credentials.owner, source=credentials.source
        )
    elif status >= 500:
        refused = HostError(
            f"{where}: host answered {status}",
            retry_after=_seconds(reply.headers.get("retry-after")),
        )
    else:
        refused = TransportError(f"{where}: {status} {who}: {reply.text[:PAGE_EXCERPT]}")
    refused.status = status
    refused.body = reply.text
    return refused


def _body(response: Response[Any, Any]) -> Any:
    """The JSON a call answered with, None for no content."""
    if not response.content:
        return None
    where = f"{response.raw_request.method} {response.raw_request.url.path}"
    kind = response.headers.get("content-type", "no content type")
    if "json" not in kind:
        # A sign-in page with a 200 is an authentication failure that looks
        # like success; it must not come back as an empty result.
        raise AuthError(f"{where}: expected JSON, got {kind}: {response.text[:PAGE_EXCERPT]}")
    try:
        return response.json()
    except ValueError as error:
        raise HostError(f"{where}: unreadable JSON: {response.text[:PAGE_EXCERPT]}") from error


def _unexpected(endpoint: str, response: Response[Any, Any]) -> str:
    return f"{endpoint}: not the document expected: {response.text[:PAGE_EXCERPT]}"


def _model[Doc: BaseModel](model: type[Doc], found: object, what: str) -> Doc:
    try:
        return model.model_validate(found)
    except ValidationError as error:
        excerpt = str(found)[:PAGE_EXCERPT]
        raise TransportError(f"{what}: not the document expected: {excerpt}") from error


def _parse[Doc: BaseModel](response: Response[Any, Any], model: type[Doc], endpoint: str) -> Doc:
    try:
        return model.model_validate(_body(response))
    except ValidationError as error:
        raise TransportError(_unexpected(endpoint, response)) from error


def _items[Doc: BaseModel](
    response: Response[Any, Any], model: type[Doc], endpoint: str
) -> list[Doc]:
    data = _body(response)
    if not isinstance(data, list):
        raise TransportError(_unexpected(endpoint, response))
    try:
        return [model.model_validate(item) for item in data]
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


def _already_exists(error: TransportError) -> bool:
    """Whether a 422 says a pull request for this head and base is already there."""
    message, errors = _said(error)
    words = " ".join([message, *(str(e.get("message", "")) for e in errors)])
    return "pull request already exists" in words.lower()


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
