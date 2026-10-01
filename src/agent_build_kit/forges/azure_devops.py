"""Azure DevOps as a code host.

Three things about this host shape everything below:

**Three segments, decoded.** A repo is organisation / project / repo, and the
remote percent-encodes any of them containing a space. `%20` handed to
`az repos --project` names a project that does not exist, so the identity is
decoded once, here, and every caller gets the readable form.

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

import re
from collections.abc import Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from agent_build_kit.forges.base import (
    BaseMissing,
    Label,
    PermittedCommand,
    PullRequest,
    RepoId,
    ReviewNote,
    Run,
    Stack,
    StackRefused,
)
from agent_build_kit.pipeline import az, units

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

# The REST version the pull request PATCH is made against; `az devops invoke`
# defaults to 5.0, which predates fields this relies on.
_API = "7.1"
# What `az repos pr create` says when a branch it was given is not on the host:
# TF401028 a missing reference, TF401398 a source or target that no longer exists.
_MISSING_REFERENCE = "TF401028"
_MISSING_BRANCH = "TF401398"


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
    client: str = "az"
    # Azure DevOps keeps the source branch unless the PR asked for it to go,
    # so the remote branch is ours to delete.
    deletes_head_branch_on_merge: bool = False
    # Azure DevOps has no first-class stacks, so the stack calls are never made.
    supports_stacks: bool = False
    # Annotated, not inferred: the Protocol's attribute is read-write, so a
    # narrower literal type would not satisfy it.
    denied_commands: tuple[tuple[str, ...], ...] = (
        # Denied whole, bar `permitted_commands`: `--status completed`,
        # `--auto-complete` and `--bypass-policy` all merge, so only the exact
        # shapes listed there are let through.
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
    # Abandoning or reopening a PR and toggling draft are the pipeline's own
    # calls; each flag is spelled in full with the values it may carry.
    permitted_commands: tuple[PermittedCommand, ...] = (
        PermittedCommand(
            prefix=("az", "repos", "pr", "update"),
            flags=(
                ("--id", r"\d+"),
                ("--status", "abandoned|active"),
                ("--draft", "true|false"),
                ("--org", ".+"),
                ("--organization", ".+"),
                ("--detect", ".+"),
                # `az.call` appends it to every call.
                ("--output", "json"),
            ),
        ),
    )
    requires: tuple[str, ...] = ("azure_devops.org", "azure_devops.project", "azure_devops.repo")

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

    # --- access ---------------------------------------------------------------------

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        """Whether this machine can read the repo it is configured for.

        A real read of the named repo, not `az account show`: only that proves
        the credential *and* the access to this repo, which is the question
        the check exists to answer.
        """
        try:
            az.json_out(
                ["repos", "show", "--project", repo.project, "--repository", repo.name],
                org=az.org_url(repo.account),
                run=run,
            )
        except az.AzError as error:
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
            found = az.json_out(
                ["repos", "policy", "list", "--project", repo.project],
                org=az.org_url(repo.account),
                run=run,
            )
        except az.AzError as error:
            return f"cannot tell what guards {branch}: {error}"
        return "" if found else f"no branch policy guards {branch}"

    def _api(self, repo: RepoId) -> str:
        """The repository's REST root, with the spaces a project name may
        carry encoded."""
        return (
            f"{az.org_url(repo.account)}/{quote(repo.project)}"
            f"/_apis/git/repositories/{quote(repo.name)}"
        )

    def _rest(
        self,
        repo: RepoId,
        resource: str,
        *,
        method: str = "GET",
        payload: object = None,
        run: Run | None = None,
        **route: object,
    ) -> object:
        """One REST call through `az devops invoke`.

        Not `az rest`: the extension implements PAT-else-`az login` itself,
        and `az rest` in PAT mode wants the secret in argv, where `ps` can
        read it.
        """
        args = [
            "devops",
            "invoke",
            "--area",
            "git",
            "--resource",
            resource,
            "--route-parameters",
            f"project={repo.project}",
            f"repositoryId={repo.name}",
            *(f"{name}={value}" for name, value in route.items()),
            "--http-method",
            method,
            "--api-version",
            _API,
        ]
        if payload is None:
            return az.json_out(args, org=az.org_url(repo.account), run=run)
        with az.body_file(payload) as body:
            return az.json_out([*args, "--in-file", body], org=az.org_url(repo.account), run=run)

    # --- pull requests --------------------------------------------------------------

    def list_prs(
        self, repo: RepoId, *, head_prefix: str = "", run: Run | None = None
    ) -> list[PullRequest]:
        found = az.json_out(
            [
                "repos",
                "pr",
                "list",
                "--project",
                repo.project,
                "--repository",
                repo.name,
                # Merged and abandoned included: a merge is precisely what the
                # poller is waiting for, and it is only visible here.
                "--status",
                "all",
                "--top",
                "100",
            ],
            org=az.org_url(repo.account),
            run=run,
        )
        if not isinstance(found, list):
            raise az.AzError("expected a list of pull requests")
        pulls = [_view(pull) for pull in found]
        if head_prefix:
            pulls = [p for p in pulls if p.head.startswith(head_prefix)]
        # What was said is a second call per pull request, so only the open
        # ones are asked: a merged or abandoned one is dispatched on its state,
        # and nothing said on it afterwards changes what the pipeline does.
        # On a small pool, so a poll's latency stops scaling with the open PRs
        # while the `az` process count stays bounded. `map` keeps listing order
        # and raises the first failure, so a failed read leaves no partial list.
        with ThreadPoolExecutor(max_workers=READ_POOL) as pool:
            return list(
                pool.map(
                    lambda p: p if p.state != "open" else self._said_on(repo, p, run=run), pulls
                )
            )

    def _said_on(self, repo: RepoId, pull: PullRequest, *, run: Run | None = None) -> PullRequest:
        """The pull request with what was said on it, for the poller to diff."""
        notes = _notes(self._threads(repo, pull.number, run=run), live_only=False)
        failing = tuple(
            sorted(
                _context(status)
                for status in self._statuses(repo, pull.number, run=run)
                if str(status.get("state") or "") in _FAILING
            )
        )
        return pull.model_copy(
            update={
                "conversation": tuple(note.id for note in notes),
                "comment_bodies": tuple(note.body for note in notes),
                "failing_checks": failing,
            }
        )

    def find_pr(self, repo: RepoId, *, head: str, run: Run | None = None) -> int | None:
        found = az.json_out(
            [
                "repos",
                "pr",
                "list",
                "--project",
                repo.project,
                "--repository",
                repo.name,
                "--source-branch",
                head,
                "--status",
                "all",
                "--top",
                "1",
            ],
            org=az.org_url(repo.account),
            run=run,
        )
        if not isinstance(found, list) or not found:
            return None
        try:
            return int(found[0]["pullRequestId"])
        except (KeyError, TypeError, ValueError):
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
            made = az.json_out(
                [
                    "repos",
                    "pr",
                    "create",
                    "--project",
                    repo.project,
                    "--repository",
                    repo.name,
                    "--source-branch",
                    head,
                    "--target-branch",
                    base,
                    "--title",
                    title,
                    "--description",
                    body,
                ],
                org=az.org_url(repo.account),
                run=run,
            )
        except az.AzError as error:
            # The host's words only: the message also holds the title and body.
            if _base_missing(error.stderr, base):
                raise BaseMissing(str(error)) from error
            raise
        if not isinstance(made, dict) or "pullRequestId" not in made:
            raise az.AzError(f"creating a pull request for {head} answered without an id")
        return int(made["pullRequestId"])

    def update_pr(
        self,
        repo: RepoId,
        pr: int,
        *,
        base: str = "",
        body: str = "",
        run: Run | None = None,
        open_url: az.OpenUrl | None = None,
    ) -> None:
        """Change a PR's base or body.

        The base goes through the REST API because `az repos pr update` has no
        `--target-branch`, and a PR left pointing at a branch that merged away
        shows a diff containing everything.
        """
        if base:
            # Not through `az devops invoke`: it resolves `git/pullRequests` to
            # the organisation-level location, which answers GET and refuses
            # PATCH. There is no CLI command for this either - `az repos pr
            # update` has no `--target-branch` - so the API is the only way.
            #
            # Only when it differs. GitHub takes a retarget to the branch a PR
            # already has; Azure answers 400 "This pull request already
            # targets ...", which failed every rework of a PR the pipeline had
            # already opened on the right branch.
            url = f"{self._api(repo)}/pullRequests/{pr}?api-version={_API}"
            target = f"refs/heads/{base}"
            current = az.rest("GET", url, run=run, open_url=open_url)
            if not isinstance(current, dict) or current.get("targetRefName") != target:
                az.rest("PATCH", url, payload={"targetRefName": target}, run=run, open_url=open_url)
        if body:
            az.json_out(
                ["repos", "pr", "update", "--id", str(pr), "--description", body],
                org=az.org_url(repo.account),
                run=run,
            )

    # --- stacks ---------------------------------------------------------------------

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        return None

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack:
        raise StackRefused("Azure DevOps has no stacks")

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack:
        raise StackRefused("Azure DevOps has no stacks")

    def _threads(self, repo: RepoId, pr: int, *, run: Run | None = None) -> list[dict]:
        return _values(self._rest(repo, "pullRequestThreads", pullRequestId=pr, run=run))

    def pr_files(self, repo: RepoId, pr: int, run: Run | None = None) -> list[str]:
        """The paths this pull request touches.

        Each push to the source branch makes an iteration, and what the change
        touches is what the newest one holds.
        """
        found = _values(self._rest(repo, "pullRequestIterations", pullRequestId=pr, run=run))
        numbers = [item["id"] for item in found if "id" in item]
        if not numbers:
            return []
        changes = self._rest(
            repo,
            "pullRequestIterationChanges",
            pullRequestId=pr,
            iterationId=max(numbers),
            run=run,
        )
        entries = changes.get("changeEntries") or [] if isinstance(changes, dict) else []
        return sorted(
            str(item.get("path") or "").lstrip("/")
            for change in entries
            if isinstance(change, dict) and not (item := change.get("item") or {}).get("isFolder")
            if item.get("path")
        )

    def _statuses(self, repo: RepoId, pr: int, *, run: Run | None = None) -> list[dict]:
        return _values(self._rest(repo, "pullRequestStatuses", pullRequestId=pr, run=run))

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
        made = self._rest(
            repo,
            "pullRequestThreadComments",
            method="POST",
            # commentType 1 is `text`; the default would be `unknown`.
            payload={"content": body, "parentCommentId": int(comment or 0), "commentType": 1},
            pullRequestId=pr,
            threadId=thread,
            run=run,
        )
        if not isinstance(made, dict) or "id" not in made:
            return []
        return [f"{thread}.{made['id']}"]

    def post_comment(
        self, repo: RepoId, pr: int, *, body: str, run: Run | None = None
    ) -> list[str]:
        """Say something about the pull request rather than about one note,
        which here means opening a thread with no file behind it."""
        made = self._rest(
            repo,
            "pullRequestThreads",
            method="POST",
            payload={"comments": [{"content": body, "commentType": 1}], "status": "active"},
            pullRequestId=pr,
            run=run,
        )
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
        run: Run | None = None,
    ) -> None:
        """Publish a result against the commit it was measured on.

        A commit status rather than a pull request status: the result belongs
        to one commit, and a pull request status would follow the branch as it
        moved. A restack changes the SHA, and a status on the wrong commit is
        worse than none.

        Azure splits a context into a genre and a name, so `local/tier2`
        becomes both; a context with no slash keeps abk's own genre.
        """
        genre, _, name = context.rpartition("/")
        self._rest(
            repo,
            "statuses",
            method="POST",
            payload={
                "state": "succeeded" if ok else "failed",
                # Well inside what the API accepts: an over-long description
                # loses the whole status rather than its tail.
                "description": description[:_DESCRIPTION],
                "context": {"genre": genre or "abk", "name": name},
            },
            commitId=sha,
            run=run,
        )

    def failed_check_logs(self, repo: RepoId, pull: PullRequest, run: Run | None = None) -> str:
        """What the failing checks said, for the rework that fixes them.

        A status carries a description and a link, and that is what this
        reports. No build log is fetched: the services posting here are not
        necessarily pipelines at all, and inventing a log fetch for a build
        that may not exist would put a guess in the rework's prompt.
        """
        if not pull.failing_checks:
            return ""
        parts = [
            f"{_context(status)} - {status.get('description') or 'failed'}"
            + (f"\n{url}" if (url := status.get("targetUrl")) else "")
            for status in self._statuses(repo, pull.number, run=run)
            if str(status.get("state") or "") in _FAILING
        ]
        return "\n\n".join(parts)

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        raise NotImplementedError

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        raise NotImplementedError

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        raise NotImplementedError

    def close_pr(self, repo: RepoId, pr: int, *, run: Run | None = None) -> None:
        """Abandon without merging - a satisfied unit's stale pull request.

        Through the CLI, which `permitted_commands` lets through for exactly
        this shape, and `az.json_out`, which raises `AzError` on failure: a
        close that did not happen must not read as one that did. Only the base
        retarget in `update_pr` goes through REST, having no CLI flag.
        """
        az.json_out(
            ["repos", "pr", "update", "--id", str(pr), "--status", "abandoned"],
            org=az.org_url(repo.account),
            run=run,
        )

    def delete_remote_branch(self, repo: RepoId, branch: str, run: Run | None = None) -> None:
        """Remove the source branch, which a merge here leaves behind.

        Azure refuses a ref delete that does not name the commit being
        removed, so the ref is read first. A branch that is already gone is
        not an error: the remote may have been cleaned up by hand, or by the
        completion itself when the PR asked for it.
        """
        where = ["--project", repo.project, "--repository", repo.name]
        found = az.json_out(
            ["repos", "ref", "list", "--filter", f"heads/{branch}", *where],
            org=az.org_url(repo.account),
            run=run,
        )
        refs = found if isinstance(found, list) else []
        at = next(
            (
                str(ref.get("objectId"))
                for ref in refs
                if _branch(ref.get("name")) == branch and ref.get("objectId")
            ),
            "",
        )
        if not at:
            return
        az.json_out(
            ["repos", "ref", "delete", "--name", f"heads/{branch}", "--object-id", at, *where],
            org=az.org_url(repo.account),
            run=run,
        )


FORGE = AzureDevOpsForge()


def _branch(ref: object) -> str:
    """A branch name from a ref. Azure reports `refs/heads/x`, and a base of
    `refs/heads/main` would be pushed to as a branch of that name."""
    return str(ref or "").removeprefix("refs/heads/")


def _decision(reviewers: list[dict]) -> str:
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
        if reviewer.get("isContainer"):
            continue
        try:
            vote = int(reviewer.get("vote", 0))
        except (TypeError, ValueError):
            continue
        if vote < 0:
            return "changes_requested"
    return ""


def _view(pull: dict) -> PullRequest:
    """One pull request as the pipeline needs to see it.

    `status` is the only field that says whether this was merged.
    `mergeStatus: succeeded` means "can be merged" and is set on open pull
    requests, and `lastMergeCommit` is populated on them too - reading either
    as proof would mark every open PR merged, restacking its children and
    deleting their branches.
    """
    status = str(pull.get("status") or "")
    return PullRequest(
        number=int(pull["pullRequestId"]),
        head=_branch(pull.get("sourceRefName")),
        base=_branch(pull.get("targetRefName")),
        state=(
            units.MERGED
            if status == "completed"
            else units.CLOSED
            if status == "abandoned"
            else "open"
        ),
        draft=bool(pull.get("isDraft")),
        # `null`, not `[]`, when a pull request has none.
        labels=tuple(sorted(str(label.get("name", "")) for label in pull.get("labels") or [])),
        review_decision=_decision(pull.get("reviewers") or []),
        # `conversation` and `failing_checks` stay empty until the review
        # round-trip and the status checks land: both need a call per pull
        # request, and an empty answer here means "nothing new", which is the
        # safe reading while the forge is unfinished.
    )


def _notes(threads: list[dict], *, live_only: bool = False) -> list[ReviewNote]:
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
        number = thread.get("id")
        context = thread.get("threadContext") or {}
        start = context.get("rightFileStart") or {}
        # Nothing goes stale here on its own, the way GitHub reports
        # `line: null` once the code a comment sat on has changed. A thread
        # the reviewer resolved is the signal in its place.
        live = str(thread.get("status") or "") == "active"
        if live_only and not live:
            continue
        for comment in thread.get("comments") or []:
            if comment.get("commentType") == "system" or comment.get("isDeleted"):
                continue
            notes.append(
                ReviewNote(
                    id=f"{number}.{comment.get('id')}",
                    body=str(comment.get("content") or ""),
                    path=str(context.get("filePath") or "").lstrip("/"),
                    line=start.get("line"),
                    live=live,
                )
            )
    return notes


def _values(answered: object) -> list[dict]:
    """The list in a REST answer. Azure wraps one in `value`, and `az repos`
    hands the bare list back - both shapes reach here."""
    found = answered.get("value") if isinstance(answered, dict) else answered
    return [item for item in found if isinstance(item, dict)] if isinstance(found, list) else []


def _context(status: dict) -> str:
    """A status's name as one string, the way a branch policy names it."""
    context = status.get("context") or {}
    genre = str(context.get("genre") or "")
    name = str(context.get("name") or "")
    return f"{genre}/{name}" if genre else name
