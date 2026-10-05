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

import logging
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
# What removing a label the pull request does not carry says.
_LABEL_ABSENT = "could not be found"

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
    ci_name: str = "Azure Pipelines"

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
        failing_evaluations, cancelled_evaluations = self._split_evaluations(
            repo, pull.number, run=run
        )
        failing = tuple(
            sorted(
                [
                    _context(status)
                    for status in _latest_statuses(self._statuses(repo, pull.number, run=run))
                    if str(status.get("state") or "") in _FAILING
                ]
                + [_policy_name(item) for item in failing_evaluations]
            )
        )
        cancelled = tuple(sorted(_policy_name(item) for item in cancelled_evaluations))
        return pull.model_copy(
            update={
                "conversation": tuple(note.id for note in notes),
                "comment_bodies": tuple(note.body for note in notes),
                "failing_checks": failing,
                "cancelled_checks": cancelled,
            }
        )

    def _split_evaluations(
        self, repo: RepoId, pr: int, *, run: Run | None = None
    ) -> tuple[list[dict], list[dict]]:
        """The failing build evaluations, apart from those whose build was cancelled.

        Both are `rejected` on the policy; only the build says which it was.
        An evaluation with no build to ask about is a failure.
        """
        failing: list[dict] = []
        cancelled: list[dict] = []
        for item in self._failing_evaluations(repo, pr, run=run):
            build = (item.get("context") or {}).get("buildId")
            if build and self._build_result(repo, build, run=run) == _BUILD_CANCELLED:
                cancelled.append(item)
            else:
                failing.append(item)
        return failing, cancelled

    def _build_result(self, repo: RepoId, build: object, *, run: Run | None = None) -> str:
        found = az.json_out(
            ["pipelines", "runs", "show", "--id", str(build), "--project", repo.project],
            org=az.org_url(repo.account),
            run=run,
        )
        return str(found.get("result") or "") if isinstance(found, dict) else ""

    def _failing_evaluations(self, repo: RepoId, pr: int, *, run: Run | None = None) -> list[dict]:
        """The build policy evaluations this pull request is failing.

        A policy evaluation is a different resource from a status: a branch
        policy's build reports here and never as a status.
        """
        found = az.json_out(
            ["repos", "pr", "policy", "list", "--id", str(pr)],
            org=az.org_url(repo.account),
            run=run,
        )
        return [
            item
            for item in (found if isinstance(found, list) else [])
            if isinstance(item, dict)
            and str(item.get("status") or "") in _POLICY_FAILING
            and _policy_type(item) == _BUILD_POLICY_TYPE
        ]

    def find_pr(
        self, repo: RepoId, *, head: str, status: str = "all", run: Run | None = None
    ) -> int | None:
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
                status,
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
        self._rest(repo, "statuses", method="POST", payload=payload, commitId=sha, run=run)
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
            self._rest(
                repo,
                "pullRequestStatuses",
                method="POST",
                payload=payload,
                pullRequestId=number,
                run=run,
            )
        except az.AzError as error:
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
        _, cancelled = self._split_evaluations(repo, pull.number, run=run)
        for item in cancelled:
            az.json_out(
                [
                    "repos",
                    "pr",
                    "policy",
                    "queue",
                    "--id",
                    str(pull.number),
                    "--evaluation-id",
                    str(item.get("evaluationId")),
                ],
                org=az.org_url(repo.account),
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
            for status in _latest_statuses(self._statuses(repo, pull.number, run=run))
            if str(status.get("state") or "") in _FAILING
        ]
        failing, _ = self._split_evaluations(repo, pull.number, run=run)
        for item in failing:
            build = (item.get("context") or {}).get("buildId")
            parts.append(
                f"{_policy_name(item)} - build policy {item.get('status')}"
                + (
                    f"\n{az.org_url(repo.account)}/{quote(repo.project)}"
                    f"/_build/results?buildId={build}"
                    if build
                    else ""
                )
            )
        return "\n\n".join(parts)

    def add_label(
        self,
        repo: RepoId,
        pr: int,
        label: Label,
        *,
        run: Run | None = None,
        open_url: az.OpenUrl | None = None,
    ) -> None:
        """Tag a pull request. Azure DevOps keeps no colour or description, so
        only the name is sent; a name already there, in any case, is kept."""
        self._rest(
            repo,
            "pullRequestLabels",
            method="post",
            payload={"name": label.name},
            run=run,
            pullRequestId=pr,
        )

    def set_exclusive_label(
        self,
        repo: RepoId,
        pr: int,
        label: Label,
        *,
        family: Collection[str],
        run: Run | None = None,
        open_url: az.OpenUrl | None = None,
    ) -> None:
        present = self._labels(repo, pr, run)
        held = {item["name"].casefold() for item in present}
        if label.name.casefold() not in held:
            self.add_label(repo, pr, label, run=run, open_url=open_url)
        wanted = {name.casefold() for name in family} - {label.name.casefold()}
        for item in present:
            if item["name"].casefold() in wanted:
                self.remove_label(repo, pr, item["name"], run=run, open_url=open_url)

    def remove_label(
        self,
        repo: RepoId,
        pr: int,
        name: str,
        *,
        run: Run | None = None,
        open_url: az.OpenUrl | None = None,
    ) -> None:
        """Untag by name, one request with nothing looked up first. A label
        that is not there returns normally; any other refusal raises."""
        try:
            self._rest(
                repo,
                "pullRequestLabels",
                method="delete",
                run=run,
                pullRequestId=pr,
                labelIdOrName=name,
            )
        except az.AzError as error:
            if _LABEL_ABSENT not in error.stderr:
                raise

    def _labels(self, repo: RepoId, pr: int, run: Run | None) -> list[dict]:
        """The labels on a pull request, from the labels resource: the pull
        request document itself carries none."""
        answer = self._rest(repo, "pullRequestLabels", method="get", run=run, pullRequestId=pr)
        values = answer.get("value") if isinstance(answer, dict) else None
        return [item for item in values or [] if isinstance(item, dict) and item.get("name")]

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
        mergeable=_MERGEABLE.get(str(pull.get("mergeStatus") or "")),
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


def _policy_type(evaluation: dict) -> str:
    """The id of the policy type an evaluation is of."""
    kind = (evaluation.get("configuration") or {}).get("type") or {}
    return str(kind.get("id") or "")


def _latest_statuses(statuses: list[dict]) -> list[dict]:
    """The newest status of each genre and name.

    Every post is a status of its own and the listing returns them all; only
    the latest of a context is the one in force, so a failure a later result
    superseded is not a failing check.
    """
    latest: dict[tuple[str, str], dict] = {}
    for status in sorted(statuses, key=lambda s: int(s.get("id") or 0)):
        context = status.get("context") or {}
        latest[(str(context.get("genre") or ""), str(context.get("name") or ""))] = status
    return list(latest.values())


def _policy_name(evaluation: dict) -> str:
    """A policy evaluation's name: the build it runs, else the policy's type."""
    configuration = evaluation.get("configuration") or {}
    settings = configuration.get("settings") or {}
    kind = configuration.get("type") or {}
    return str(settings.get("displayName") or kind.get("displayName") or "build policy")


def _context(status: dict) -> str:
    """A status's name as one string, the way a branch policy names it."""
    context = status.get("context") or {}
    genre = str(context.get("genre") or "")
    name = str(context.get("name") or "")
    return f"{genre}/{name}" if genre else name
