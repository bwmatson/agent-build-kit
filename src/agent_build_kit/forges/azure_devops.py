"""Azure DevOps as a code host.

Three things about this host shape everything below:

**Three segments, decoded.** A repo is organisation / project / repo, and the
remote percent-encodes any of them containing a space. The identity is decoded
once, here, and quoted into each REST path, so a `%20` is never quoted a second
time into a project that does not exist.

**A merge is only a merge when `status` says so.** An open pull request
carries `mergeStatus: succeeded` and a populated `lastMergeCommit` exactly as a
completed one does — verified against six real pull requests, three of each.
Reading either as proof marks every open PR merged, which restacks its children
and deletes their branches.

**Merging has a wide surface.** GitHub has one command; here a PR is completed
by `az repos pr update --status completed`, approved by `az repos pr set-vote`,
unblocked by `az repos policy`, and all of it is reachable through `az rest`
and `az devops invoke`. `denied_commands` names every one of them, and the
registry's union means they are refused in a GitHub checkout too.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

import httpx
from pydantic import BaseModel, ValidationError

from agent_build_kit.forges.azure_models import (
    BuildDoc,
    ChangesDoc,
    EvaluationDoc,
    IterationDoc,
    LabelDoc,
    PullRequestDoc,
    RefDoc,
    RefUpdateDoc,
    ReviewerDoc,
    StatusDoc,
    ThreadDoc,
)
from agent_build_kit.forges.base import (
    BaseMissing,
    Check,
    CheckStatus,
    FileChange,
    Label,
    PullRequest,
    RepoId,
    ReviewNote,
    Run,
    Stack,
    StackRefused,
    failing_names,
)
from agent_build_kit.forges.transport import (
    AZURE_CLI_SOURCE,
    PAGE_EXCERPT,
    TRANSIENT,
    AuthError,
    NotFound,
    Response,
    Transport,
    TransportError,
    credential_for,
    forget_credential,
)
from agent_build_kit.pipeline import units

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

_HOST = "https://dev.azure.com"
# The REST version every call is made against, and the one policy evaluations
# are only served under.
_API = "7.1"
_API_EVALUATIONS = "7.1-preview.1"
# The most the list endpoints give a page of.
_PAGE = 100
# What creating a pull request says when a branch it was given is not on the host:
# TF401028 a missing reference, TF401398 a source or target that no longer exists.
_MISSING_REFERENCE = "TF401028"
_MISSING_BRANCH = "TF401398"
# TF401179: an active pull request for this source and target already exists.
_ALREADY_EXISTS = "TF401179"
# The all-zero object id a ref is "updated" to when it is deleted.
_NO_OBJECT = "0" * 40
# What the host calls a comment's type, in a request: 1 is `text`, where the
# default would be `unknown`.
_TEXT_COMMENT = 1

log = logging.getLogger(__name__)

# `mergeStatus` as a conflict answer: only `succeeded` and `conflicts` are
# definite. `queued` and `notSet` are the host working it out, and
# `rejectedByPolicy` and `failure` say nothing about conflicts, so a rework
# sent for any of them could not fix what it was sent for.
_MERGEABLE = {"succeeded": True, "conflicts": False}

# A build policy evaluation that has finished badly. `running` and `queued` are
# waiting, and `approved` and `notApplicable` are passing.
_POLICY_FAILING = ("rejected", "broken")

# How a build says it was cancelled, in its `result`. The policy evaluation says
# only `rejected`, so the build is asked.
_BUILD_CANCELLED = "canceled"

# What a build policy evaluation came to. `notApplicable` is not a check at all.
_POLICY_PASSING = "approved"
_POLICY_NOT_APPLICABLE = "notApplicable"

# The policy type of build validation. `az repos pr policy list` evaluates every
# policy on the target branch - reviewers, work item linking, comments, status -
# and a pull request waiting for its approval is `rejected` on those too, which
# no rework can fix.
_BUILD_POLICY_TYPE = "0609b952-1397-4640-95ec-e00a01b2c241"


def _base_missing(stderr: str, base: str) -> bool:
    """Whether the host's refusal says the *target* branch is gone.

    TF401028 names the reference it could not find, and is a base problem only
    when that is the base: a missing source would be a different failure.
    TF401398 says "source and/or target" without telling which, and the source
    was pushed moments before, so it is read as the target.
    """
    return _MISSING_BRANCH in stderr or (
        _MISSING_REFERENCE in stderr and f"refs/heads/{base}" in stderr
    )


# `pending` and `notSet` are waiting, not failing: read as failures they would
# send a unit back for rework while its build was still running.
_FAILING = ("failed", "error")
_STATUS_NOT_APPLICABLE = "notApplicable"
_STATUS_CHECKS = {
    "succeeded": CheckStatus.PASSED,
    "failed": CheckStatus.FAILED,
    "error": CheckStatus.FAILED,
    "pending": CheckStatus.PENDING,
    "notSet": CheckStatus.PENDING,
}

# A status description well inside what the API accepts. Over the limit the
# whole status is refused, not its tail.
_DESCRIPTION = 950

# `git@ssh.dev.azure.com:v3/<org>/<project>/<repo>`, with or without the
# ssh:// scheme, and `https://[user@]dev.azure.com/<org>/<project>/_git/<repo>`.
# Anchored on the host, which is why this forge is asked before GitHub's
# pattern, which accepts any `alias:owner/name`.
_SSH = re.compile(
    r"^(?:ssh://)?[\w.-]*@?ssh\.dev\.azure\.com[:/]v3/"
    r"(?P<org>[^/]+)/(?P<project>[^/]+)/(?P<repo>[^/]+?)/?$"
)
_HTTPS = re.compile(
    r"^https://(?:[^@/]+@)?dev\.azure\.com/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/"
    r"(?P<repo>[^/]+?)/?$"
)


# How many pull requests' conversations and checks are read at once.
READ_POOL = 4


class AzureDevOpsForge:
    name: str = "azure_devops"
    implemented: bool = True
    client: str | None = "az"
    # Azure DevOps keeps the source branch unless the PR asked for it to go,
    # so the remote branch is ours to delete.
    deletes_head_branch_on_merge: bool = False
    # Azure DevOps has no first-class stacks, so the stack calls are never made.
    supports_stacks: bool = False
    # Annotated, not inferred: the Protocol's attribute is read-write, so a
    # narrower literal type would not satisfy it.
    denied_commands: tuple[tuple[str, ...], ...] = (
        ("az", "repos", "pr", "update"),
        ("az", "repos", "pr", "set-vote"),
        ("az", "repos", "policy"),
        # The raw escapes, which reach all of the above.
        ("az", "rest"),
        ("az", "devops", "invoke"),
    )
    read_commands: tuple[tuple[str, ...], ...] = (
        ("az", "repos", "pr", "show"),
        ("az", "repos", "pr", "list"),
        ("az", "repos", "pr", "policy", "list"),
    )
    requires: tuple[str, ...] = ("azure_devops.org", "azure_devops.project", "azure_devops.repo")
    ci_name: str = "Azure Pipelines"
    description_limit: int = 4_000

    def __init__(self, http: httpx.BaseTransport | None = None) -> None:
        # The transport every REST call goes through; None is the network.
        self.http = http
        self._transports: dict[str, Transport] = {}
        self._lock = threading.Lock()

    # --- identity -------------------------------------------------------------------

    def parse_remote(self, url: str) -> RepoId | None:
        match = _SSH.match(url.strip()) or _HTTPS.match(url.strip())
        if not match:
            return None
        return RepoId(
            forge=self.name,
            account=unquote(match["org"]),
            project=unquote(match["project"]),
            name=unquote(match["repo"]),
        )

    def identity(self, repo: RepoConfig) -> RepoId:
        """The repo's identity from its own block in abk.yaml.

        Not from `slug`: three segments re-split from one string is exactly
        the ambiguity a project name containing a slash would break.
        """
        entry = repo.azure_devops
        return RepoId(forge=self.name, account=entry.org, project=entry.project, name=entry.repo)

    def config_entry(self, repo: RepoId) -> dict[str, object]:
        return {
            "azure_devops": {
                "org": repo.account,
                "project": repo.project,
                "repo": repo.name,
            }
        }

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str:
        base = (
            f"https://dev.azure.com/{quote(repo.account)}/{quote(repo.project)}"
            f"/_git/{quote(repo.name)}"
        )
        return f"{base}/pullrequest/{pr}" if pr else base

    # --- the wire -------------------------------------------------------------------

    def _transport(self, account: str, run: Run | None) -> Transport:
        """The connection for one organisation, rebuilt when its credential is
        read again: `_call` drops an `az` token the host rejected, since it
        expires, so the next read runs `az` for a fresh one."""
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
        path: str,
        *,
        version: str = _API,
        params: dict[str, str] | None = None,
        json: Any = None,
        run: Run | None = None,
    ) -> Response:
        """One REST call, `path` being under the project's `_apis/`.

        A token from the `az` session that the host rejects has most likely
        expired, so it is dropped and the call made once more with a fresh one.
        A PAT stays cached: a rejected PAT is rejected again.
        """
        url = f"/{quote(repo.account)}/{quote(repo.project)}/_apis/{path}"
        query = {"api-version": version, **(params or {})}
        transport = self._transport(repo.account, run)
        try:
            return transport.request(method, url, json=json, params=query)
        except AuthError:
            if transport.credentials.source != AZURE_CLI_SOURCE:
                raise
        forget_credential(self.name, repo.account)
        return self._transport(repo.account, run).request(method, url, json=json, params=query)

    def _git(self, repo: RepoId, method: str, tail: str = "", **kwargs: Any) -> Response:
        """One REST call on the repository itself."""
        path = f"git/repositories/{quote(repo.name)}" + (f"/{tail}" if tail else "")
        return self._call(repo, method, path, **kwargs)

    # --- access ---------------------------------------------------------------------

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        """Whether this machine can read the repo it is configured for.

        A real read of the named repo: only that proves the credential *and*
        the access to this repo, which is the question the check exists to
        answer.
        """
        try:
            self._git(repo, "GET", run=run)
        except TRANSIENT:
            raise
        except TransportError as error:
            return f"cannot read {repo.name} in {repo.project}: {error}"
        return ""

    def access_fix(self, repo: RepoId) -> str:
        return (
            f"az login (or set AZURE_DEVOPS_EXT_PAT) for {repo.account}, "
            f"with access to {repo.project}"
        )

    def merge_guard(self, repo: RepoId, *, branch: str, run: Run | None = None) -> str:
        """What stops a merge on the server, or "" when nothing does.

        A project with no branch policy answers honestly: nothing does — which
        is worth saying out loud, because the command hook is then the only
        thing between an agent and its own merge.
        """
        try:
            found = self._call(repo, "GET", "policy/configurations", run=run)
        except TRANSIENT:
            raise
        except TransportError as error:
            return f"cannot tell what guards {branch}: {error}"
        values = found.data.get("value") if isinstance(found.data, dict) else None
        return "" if values else f"no branch policy guards {branch}"

    # --- pull requests --------------------------------------------------------------

    def list_prs(
        self, repo: RepoId, *, head_prefix: str = "", run: Run | None = None
    ) -> list[PullRequest]:
        # Merged and abandoned included: a merge is precisely what the poller is
        # waiting for, and it is only visible here.
        docs = self._pull_docs(repo, {"searchCriteria.status": "all"}, run=run)
        projects = {doc.pull_request_id: doc.repository.project.id for doc in docs}
        pulls = [_view(doc) for doc in docs]
        if head_prefix:
            pulls = [p for p in pulls if p.head.startswith(head_prefix)]
        # What was said is a few calls per pull request, so only the open ones
        # are asked: a merged or abandoned one is dispatched on its state, and
        # nothing said on it afterwards changes what the pipeline does.
        # On a small pool, so a poll's latency stops scaling with the open PRs
        # while the requests in flight stay bounded. `map` keeps listing order
        # and raises the first failure, so a failed read leaves no partial list.
        with ThreadPoolExecutor(max_workers=READ_POOL) as pool:
            return list(
                pool.map(
                    lambda p: (
                        p if p.state != "open" else self._said_on(repo, p, projects[p.number], run)
                    ),
                    pulls,
                )
            )

    def _pull_docs(
        self, repo: RepoId, criteria: dict[str, str], *, limit: int = 0, run: Run | None = None
    ) -> list[PullRequestDoc]:
        """The pull requests matching `criteria`, every page of them, or the
        first `limit` when one is given."""
        docs: list[PullRequestDoc] = []
        while True:
            page = _items(
                self._git(
                    repo,
                    "GET",
                    "pullrequests",
                    params={**criteria, "$top": str(limit or _PAGE), "$skip": str(len(docs))},
                    run=run,
                ),
                PullRequestDoc,
                "GET pullrequests",
            )
            docs.extend(page)
            if limit or len(page) < _PAGE:
                return docs

    def _pull_doc(self, repo: RepoId, pr: int, *, run: Run | None = None) -> PullRequestDoc:
        route = f"pullrequests/{pr}"
        return _parse(self._git(repo, "GET", route, run=run), PullRequestDoc, f"GET {route}")

    def _said_on(
        self, repo: RepoId, pull: PullRequest, project: str, run: Run | None = None
    ) -> PullRequest:
        """The pull request with what was said on it, for the poller to diff."""
        notes = _notes(self._threads(repo, pull.number, run=run), live_only=False)
        checks = [
            Check(
                name=_context(status),
                status=_STATUS_CHECKS.get(status.state, CheckStatus.PENDING),
                url=status.target_url or "",
            )
            for status in _latest_statuses(self._statuses(repo, pull.number, run=run))
            if status.state != _STATUS_NOT_APPLICABLE
        ]
        for item in self._build_evaluations(repo, pull.number, project, run=run):
            if item.status == _POLICY_NOT_APPLICABLE:
                continue
            checks.append(
                Check(
                    name=_policy_name(item),
                    status=self._evaluation_status(repo, item, run=run),
                    url=_build_url(repo, item.context.build_id if item.context else None),
                )
            )
        return pull.model_copy(
            update={
                "conversation": tuple(note.id for note in notes),
                "comment_bodies": tuple(note.body for note in notes),
                "checks": tuple(checks),
            }
        )

    def _evaluation_status(
        self, repo: RepoId, item: EvaluationDoc, *, run: Run | None = None
    ) -> CheckStatus:
        if item.status == _POLICY_PASSING:
            return CheckStatus.PASSED
        if item.status not in _POLICY_FAILING:
            # running, queued, or a word this forge does not know: waiting.
            return CheckStatus.PENDING
        build = item.context.build_id if item.context else None
        if build and self._build_result(repo, build, run=run) == _BUILD_CANCELLED:
            return CheckStatus.CANCELLED
        return CheckStatus.FAILED

    def _split_evaluations(
        self, repo: RepoId, pr: int, project: str, *, run: Run | None = None
    ) -> tuple[list[EvaluationDoc], list[EvaluationDoc]]:
        """The failing build evaluations, apart from those whose build was cancelled.

        Both are `rejected` on the policy; only the build says which it was.
        An evaluation with no build to ask about is a failure.
        """
        failing: list[EvaluationDoc] = []
        cancelled: list[EvaluationDoc] = []
        for item in self._build_evaluations(repo, pr, project, run=run):
            if item.status not in _POLICY_FAILING:
                continue
            status = self._evaluation_status(repo, item, run=run)
            (cancelled if status == CheckStatus.CANCELLED else failing).append(item)
        return failing, cancelled

    def _build_result(self, repo: RepoId, build: int, *, run: Run | None = None) -> str:
        route = f"build/builds/{build}"
        found = self._call(repo, "GET", route, run=run)
        return _parse(found, BuildDoc, f"GET {route}").result or ""

    def _build_evaluations(
        self, repo: RepoId, pr: int, project: str, *, run: Run | None = None
    ) -> list[EvaluationDoc]:
        """The build policy evaluations of this pull request, whatever they came to.

        A policy evaluation is a different resource from a status: a branch
        policy's build reports here and never as a status. The list is paged by
        `$top`/`$skip` (Policy Evaluations - List, 7.1-preview.1, documents no
        continuation token), and a failing one may be on the last page.
        """
        artifact = f"vstfs:///CodeReview/CodeReviewId/{project}/{pr}"
        found: list[EvaluationDoc] = []
        while True:
            answer = self._call(
                repo,
                "GET",
                "policy/evaluations",
                version=_API_EVALUATIONS,
                params={"artifactId": artifact, "$top": str(_PAGE), "$skip": str(len(found))},
                run=run,
            )
            page = _items(answer, EvaluationDoc, "GET policy/evaluations")
            found += page
            # An empty page, not a short one: the host may cap a page below `$top`.
            if not page:
                break
        return [item for item in found if item.configuration.type.id == _BUILD_POLICY_TYPE]

    def find_pr(
        self, repo: RepoId, *, head: str, status: str = "all", run: Run | None = None
    ) -> int | None:
        found = self._pull_docs(
            repo,
            {"searchCriteria.sourceRefName": f"refs/heads/{head}", "searchCriteria.status": status},
            limit=1,
            run=run,
        )
        return found[0].pull_request_id if found else None

    def comment_exists(
        self,
        repo: RepoId,
        pr: int,
        marker: str,
        body: str,
        *,
        reply_to: str | None = None,
        run: Run | None = None,
    ) -> str | None:
        thread_id, _, parent = (reply_to or "").partition(".")
        for thread in self._threads(repo, pr, run=run):
            if reply_to is not None and str(thread.id) != thread_id:
                continue
            for comment in thread.comments:
                if reply_to is not None and comment.parent_comment_id != int(parent or 0):
                    continue
                if comment.is_deleted:
                    continue
                if comment.content == body and marker in body:
                    return f"{thread.id}.{comment.id}"
        return None

    def create_pr(
        self,
        repo: RepoId,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        run: Run | None = None,
    ) -> int:
        try:
            made = self._git(
                repo,
                "POST",
                "pullrequests",
                json={
                    "sourceRefName": f"refs/heads/{head}",
                    "targetRefName": f"refs/heads/{base}",
                    "title": title,
                    "description": body,
                },
                run=run,
            )
        except TransportError as error:
            # The host's words only: the request, which holds the title and
            # body, is not in the error.
            if _base_missing(str(error), base):
                raise BaseMissing(str(error)) from error
            if _ALREADY_EXISTS in str(error):
                existing = self.find_pr(repo, head=head, status="active", run=run)
                if existing is not None:
                    return existing
            raise
        return _parse(made, PullRequestDoc, "POST pullrequests").pull_request_id

    def update_pr(
        self,
        repo: RepoId,
        pr: int,
        *,
        base: str = "",
        body: str = "",
        run: Run | None = None,
    ) -> None:
        """Change a PR's base or body.

        A PR left pointing at a branch that merged away shows a diff containing
        everything, which is why the base is retargeted at all.
        """
        route = f"pullrequests/{pr}"
        if base:
            # Only when it differs. GitHub takes a retarget to the branch a PR
            # already has; Azure answers 400 "This pull request already
            # targets ...", which failed every rework of a PR the pipeline had
            # already opened on the right branch.
            target = f"refs/heads/{base}"
            if self._pull_doc(repo, pr, run=run).target_ref_name != target:
                self._git(repo, "PATCH", route, json={"targetRefName": target}, run=run)
        if body:
            # Advisory: a body that is not updated is not worth failing the unit
            # over, least of all after the pull request exists.
            try:
                self._git(
                    repo,
                    "PATCH",
                    route,
                    json={"description": body},
                    run=run,
                )
            except TRANSIENT:
                raise
            except TransportError as error:
                log.warning("could not update the body of pull request %s: %s", pr, error)

    # --- stacks ---------------------------------------------------------------------

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        return None

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack:
        raise StackRefused("Azure DevOps has no stacks")

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack:
        raise StackRefused("Azure DevOps has no stacks")

    def _threads(self, repo: RepoId, pr: int, *, run: Run | None = None) -> list[ThreadDoc]:
        route = f"pullrequests/{pr}/threads"
        return _items(self._git(repo, "GET", route, run=run), ThreadDoc, f"GET {route}")

    def pr_changes(self, repo: RepoId, pr: int) -> list[FileChange]:
        """Azure DevOps reports no per-file line counts, so no size is known."""
        return []

    def pr_files(self, repo: RepoId, pr: int, run: Run | None = None) -> list[str]:
        """The paths this pull request touches.

        Each push to the source branch makes an iteration, and what the change
        touches is what the newest one holds.
        """
        route = f"pullrequests/{pr}/iterations"
        found = _items(self._git(repo, "GET", route, run=run), IterationDoc, f"GET {route}")
        if not found:
            return []
        route = f"{route}/{max(item.id for item in found)}/changes"
        paths: list[str] = []
        params: dict[str, str] = {}
        while True:
            changes = _parse(
                self._git(repo, "GET", route, params=params, run=run), ChangesDoc, f"GET {route}"
            )
            paths += [
                change.item.path.lstrip("/")
                for change in changes.change_entries or []
                if change.item and change.item.path and not change.item.is_folder
            ]
            if not changes.next_skip:
                return sorted(paths)
            params = {"$skip": str(changes.next_skip), "$top": str(changes.next_top)}

    def _statuses(self, repo: RepoId, pr: int, *, run: Run | None = None) -> list[StatusDoc]:
        route = f"pullrequests/{pr}/statuses"
        return _items(self._git(repo, "GET", route, run=run), StatusDoc, f"GET {route}")

    # --- cleanup --------------------------------------------------------------------

    def review_notes(self, repo: RepoId, pr: int, run: Run | None = None) -> list[ReviewNote]:
        """The reviewer's words on a pull request, as threads.

        Everything a reviewer wrote lives in one of these, anchored to a line
        or not. What is left out is the server talking to itself - see
        `_notes`.
        """
        return _notes(self._threads(repo, pr, run=run))

    def post_reply(
        self, repo: RepoId, pr: int, *, note_id: str, body: str, run: Run | None = None
    ) -> list[str]:
        """Answer one note, in the thread it was written in.

        One comment, not a review of its own: there is no second object to
        record, unlike GitHub, where a reply creates a bodyless review.
        """
        thread, _, comment = note_id.partition(".")
        made = self._git(
            repo,
            "POST",
            f"pullrequests/{pr}/threads/{thread}/comments",
            json={
                "content": body,
                "parentCommentId": int(comment or 0),
                "commentType": _TEXT_COMMENT,
            },
            run=run,
        ).data
        if not isinstance(made, dict) or "id" not in made:
            return []
        return [f"{thread}.{made['id']}"]

    def post_comment(
        self, repo: RepoId, pr: int, *, body: str, run: Run | None = None
    ) -> list[str]:
        """Say something about the pull request rather than about one note,
        which here means opening a thread with no file behind it."""
        made = self._git(
            repo,
            "POST",
            f"pullrequests/{pr}/threads",
            json={
                "comments": [{"content": body, "commentType": _TEXT_COMMENT}],
                "status": "active",
            },
            run=run,
        ).data
        if not isinstance(made, dict) or "id" not in made:
            return []
        comments = made.get("comments") or [{}]
        return [f"{made['id']}.{comments[0].get('id', 1)}"]

    def post_status(
        self,
        repo: RepoId,
        *,
        sha: str,
        ok: bool,
        context: str,
        description: str,
        head: str = "",
        run: Run | None = None,
    ) -> None:
        """Publish a result against the commit it was measured on.

        The commit status is the record: the result belongs to one commit, and
        a restack changes the SHA, so a status on the wrong commit is worse than
        none. Azure shows only a pull request's own statuses, so the open pull
        request for `head` gets the same result too, where a branch policy or a
        person reading the pull request will see it. That one follows the
        branch, and each result replaces the last of its context.

        Azure splits a context into a genre and a name, so `local/tier2`
        becomes both; a context with no slash keeps abk's own genre.
        """
        genre, _, name = context.rpartition("/")
        payload = {
            "state": "succeeded" if ok else "failed",
            # Well inside what the API accepts: an over-long description
            # loses the whole status rather than its tail.
            "description": description[:_DESCRIPTION],
            "context": {"genre": genre or "abk", "name": name},
        }
        try:
            self._git(repo, "POST", f"commits/{quote(sha)}/statuses", json=payload, run=run)
        except TRANSIENT:
            raise
        except TransportError as error:
            log.warning("could not post %s on %s: %s", context, sha, error)
            return
        if head:
            self._post_pr_status(repo, head, payload, run=run)

    def _post_pr_status(
        self, repo: RepoId, head: str, payload: dict, *, run: Run | None = None
    ) -> None:
        """The same status on the open pull request for `head`, if there is one.

        Never fatal: a completed or abandoned pull request takes no status and
        the host may refuse for lack of permission, and the commit status that
        was already posted is the record that matters.
        """
        # Active only: a completed or abandoned pull request takes no status.
        number = self.find_pr(repo, head=head, status="active", run=run)
        if number is None:
            return
        try:
            self._git(repo, "POST", f"pullrequests/{number}/statuses", json=payload, run=run)
        except TRANSIENT:
            raise
        except TransportError as error:
            context = payload["context"]
            log.warning(
                "could not show %s/%s %s on the pull request for %s: %s",
                context["genre"],
                context["name"],
                payload["state"],
                head,
                error,
            )

    def rerun_checks(self, repo: RepoId, pull: PullRequest, run: Run | None = None) -> None:
        """Queue the build policy evaluations whose build was cancelled again."""
        project = self._pull_doc(repo, pull.number, run=run).repository.project.id
        _, cancelled = self._split_evaluations(repo, pull.number, project, run=run)
        for item in cancelled:
            evaluation = quote(item.evaluation_id, safe="")
            self._call(
                repo,
                "PATCH",
                f"policy/evaluations/{evaluation}",
                version=_API_EVALUATIONS,
                run=run,
            )

    def failed_check_logs(self, repo: RepoId, pull: PullRequest, run: Run | None = None) -> str:
        """What the failing checks said, for the rework that fixes them.

        A status carries a description and a link, and that is what this
        reports. No build log is fetched: the services posting here are not
        necessarily pipelines at all, and inventing a log fetch for a build
        that may not exist would put a guess in the rework's prompt.
        """
        if not failing_names(pull.checks):
            return ""
        parts = [
            f"{_context(status)} - {status.description or 'failed'}"
            + (f"\n{status.target_url}" if status.target_url else "")
            for status in _latest_statuses(self._statuses(repo, pull.number, run=run))
            if status.state in _FAILING
        ]
        project = self._pull_doc(repo, pull.number, run=run).repository.project.id
        failing, _ = self._split_evaluations(repo, pull.number, project, run=run)
        for item in failing:
            build = item.context.build_id if item.context else None
            parts.append(
                f"{_policy_name(item)} - build policy {item.status}"
                + (f"\n{_build_url(repo, build)}" if build else "")
            )
        return "\n\n".join(parts)

    def add_label(self, repo: RepoId, pr: int, label: Label, *, run: Run | None = None) -> None:
        """Tag a pull request. Azure DevOps keeps no colour or description, so
        only the name is sent; a name already there, in any case, is kept."""
        self._git(repo, "POST", f"pullrequests/{pr}/labels", json={"name": label.name}, run=run)

    def set_exclusive_label(
        self,
        repo: RepoId,
        pr: int,
        label: Label,
        *,
        family: Collection[str],
        run: Run | None = None,
    ) -> None:
        present = self._labels(repo, pr, run)
        held = {item.name.casefold() for item in present}
        if label.name.casefold() not in held:
            self.add_label(repo, pr, label, run=run)
        wanted = {name.casefold() for name in family} - {label.name.casefold()}
        for item in present:
            if item.name.casefold() in wanted:
                self.remove_label(repo, pr, item.name, run=run)

    def remove_label(self, repo: RepoId, pr: int, name: str, *, run: Run | None = None) -> None:
        """Untag by name, one request with nothing looked up first. A label
        that is not there returns normally; any other refusal raises."""
        label = quote(name, safe="")
        try:
            self._git(repo, "DELETE", f"pullrequests/{pr}/labels/{label}", run=run)
        except NotFound:
            pass

    def _labels(self, repo: RepoId, pr: int, run: Run | None) -> list[LabelDoc]:
        """The labels on a pull request, from the labels resource: the pull
        request document itself carries none."""
        route = f"pullrequests/{pr}/labels"
        return _items(self._git(repo, "GET", route, run=run), LabelDoc, f"GET {route}")

    def set_draft(self, repo: RepoId, pr: int, draft: bool, *, run: Run | None = None) -> None:
        """Make a pull request a draft or publish it, writing only on a change."""
        if self._pull_doc(repo, pr, run=run).is_draft == draft:
            return
        self._git(repo, "PATCH", f"pullrequests/{pr}", json={"isDraft": draft}, run=run)

    def close_pr(self, repo: RepoId, pr: int, *, run: Run | None = None) -> None:
        """Abandon without merging - a satisfied unit's stale pull request.

        A refusal raises: a close that did not happen must not read as one
        that did.
        """
        self._git(repo, "PATCH", f"pullrequests/{pr}", json={"status": "abandoned"}, run=run)

    def delete_remote_branch(self, repo: RepoId, branch: str, run: Run | None = None) -> None:
        """Remove the source branch, which a merge here leaves behind.

        Azure refuses a ref delete that does not name the commit being
        removed, so the ref is read first. A branch that is already gone is
        not an error: the remote may have been cleaned up by hand, or by the
        completion itself when the PR asked for it.
        """
        refs = _items(
            self._git(repo, "GET", "refs", params={"filter": f"heads/{branch}"}, run=run),
            RefDoc,
            "GET refs",
        )
        at = next(
            (ref.object_id for ref in refs if _branch(ref.name) == branch and ref.object_id), ""
        )
        if not at:
            return
        answer = self._git(
            repo,
            "POST",
            "refs",
            json=[{"name": f"refs/heads/{branch}", "oldObjectId": at, "newObjectId": _NO_OBJECT}],
            run=run,
        )
        # A refused delete is a 200 that says so per ref.
        for update in _items(answer, RefUpdateDoc, "POST refs"):
            if not update.success:
                raise TransportError(
                    f"POST refs: {update.name or branch} was not deleted: "
                    f"{update.update_status or 'no reason given'}"
                )


FORGE = AzureDevOpsForge()


def _parse[Doc: BaseModel](response: Response, model: type[Doc], endpoint: str) -> Doc:
    """The body as `model`, or a `TransportError` naming the endpoint and
    quoting the start of what came back."""
    try:
        return model.model_validate(response.data)
    except ValidationError as error:
        raise TransportError(_unexpected(endpoint, response)) from error


def _items[Doc: BaseModel](response: Response, model: type[Doc], endpoint: str) -> list[Doc]:
    """The documents in a list answer. Azure wraps one in `value`."""
    data = response.data
    values = data.get("value") if isinstance(data, dict) else None
    if not isinstance(values, list):
        raise TransportError(_unexpected(endpoint, response))
    try:
        return [model.model_validate(value) for value in values]
    except ValidationError as error:
        raise TransportError(_unexpected(endpoint, response)) from error


def _unexpected(endpoint: str, response: Response) -> str:
    return f"{endpoint}: not the document expected: {response.text[:PAGE_EXCERPT]}"


def _branch(ref: object) -> str:
    """A branch name from a ref. Azure reports `refs/heads/x`, and a base of
    `refs/heads/main` would be pushed to as a branch of that name."""
    return str(ref or "").removeprefix("refs/heads/")


def _decision(reviewers: list[ReviewerDoc]) -> str:
    """Whether anybody has asked for changes.

    Azure's scale is 10 approved, 5 approved with suggestions, 0 no vote, -5
    waiting for the author, -10 rejected. So a negative vote asks for
    something and 5 does not - read as rework, an approval with suggestions
    would send the unit round the loop again on every poll for as long as the
    vote stands.

    A group (`isContainer`) votes on behalf of nobody: a required-reviewers
    group sitting at -5 would rework the unit forever.
    """
    for reviewer in reviewers:
        if not reviewer.is_container and reviewer.vote < 0:
            return "changes_requested"
    return ""


def _view(pull: PullRequestDoc) -> PullRequest:
    """One pull request as the pipeline needs to see it.

    `status` is the only field that says whether this was merged.
    `mergeStatus: succeeded` means "can be merged" and is set on open pull
    requests, and `lastMergeCommit` is populated on them too - reading either
    as proof would mark every open PR merged, restacking its children and
    deleting their branches.
    """
    return PullRequest(
        number=pull.pull_request_id,
        head=_branch(pull.source_ref_name),
        base=_branch(pull.target_ref_name),
        state=(
            units.MERGED
            if pull.status == "completed"
            else units.CLOSED
            if pull.status == "abandoned"
            else "open"
        ),
        draft=pull.is_draft,
        mergeable=_MERGEABLE.get(pull.merge_status or ""),
        # `null`, not `[]`, when a pull request has none.
        labels=tuple(sorted(label.name for label in pull.labels or [])),
        review_decision=_decision(pull.reviewers),
        # `conversation` and the checks are filled in for the open ones by
        # `_said_on`: each needs calls per pull request.
    )


def _notes(threads: list[ThreadDoc], *, live_only: bool = False) -> list[ReviewNote]:
    """Every human comment in these threads, oldest first.

    What is dropped is what the server wrote itself. Azure records "the
    reference refs/heads/... was updated" on the thread list on *every push*,
    along with reviewers being added and the like, and the pipeline pushes on
    every rework and every restack - so counted as comments, each push would
    rework the unit that just pushed, and it would never stop.

    The test for that is `commentType == "system"` rather than
    `commentType == "text"`: a real comment can carry a null type, and the
    inverted rule drops a reviewer's words.

    A note's id carries its thread's, because comment ids restart at 1 in
    every thread - `1` alone would collide across a pull request's threads and
    the poller would read two different comments as one.
    """
    notes = []
    for thread in threads:
        context = thread.thread_context
        start = context.right_file_start if context else None
        # Nothing goes stale here on its own, the way GitHub reports
        # `line: null` once the code a comment sat on has changed. A thread
        # the reviewer resolved is the signal in its place.
        live = thread.status == "active"
        if live_only and not live:
            continue
        for comment in thread.comments:
            if comment.comment_type == "system" or comment.is_deleted:
                continue
            notes.append(
                ReviewNote(
                    id=f"{thread.id}.{comment.id}",
                    body=comment.content or "",
                    path=((context.file_path if context else None) or "").lstrip("/"),
                    line=start.line if start else None,
                    live=live,
                )
            )
    return notes


def _build_url(repo: RepoId, build: int | None) -> str:
    """The web link to a build, or "" where an evaluation names none."""
    if not build:
        return ""
    return f"{_HOST}/{quote(repo.account)}/{quote(repo.project)}/_build/results?buildId={build}"


def _latest_statuses(statuses: list[StatusDoc]) -> list[StatusDoc]:
    """The newest status of each genre and name.

    Every post is a status of its own and the listing returns them all; only
    the latest of a context is the one in force, so a failure a later result
    superseded is not a failing check.
    """
    latest: dict[tuple[str, str], StatusDoc] = {}
    for status in sorted(statuses, key=lambda s: s.id):
        latest[(status.context.genre or "", status.context.name)] = status
    return list(latest.values())


def _policy_name(evaluation: EvaluationDoc) -> str:
    """A policy evaluation's name: the build it runs, else the policy's type."""
    configuration = evaluation.configuration
    return str(
        configuration.settings.get("displayName")
        or configuration.type.display_name
        or "build policy"
    )


def _context(status: StatusDoc) -> str:
    """A status's name as one string, the way a branch policy names it."""
    genre = status.context.genre or ""
    return f"{genre}/{status.context.name}" if genre else status.context.name
