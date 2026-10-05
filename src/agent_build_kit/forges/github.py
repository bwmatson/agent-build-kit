"""GitHub, through the `gh` CLI.

Everything here was in the pipeline before the forges existed, and is moved
rather than rewritten: the origin pattern from `init/detect.py`, and in the
stages that follow, the `gh` calls from `wiring`, `events`, `pr_replies`,
`tier2` and the poller. `pipeline/shell.py` stays the only way to run `gh`, so
this module calls it and never `subprocess` directly.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

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
    key,
)
from agent_build_kit.pipeline import units
from agent_build_kit.pipeline.shell import GhError, gh, gh_json, gh_out

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

# What `gh pr create` says when the base branch is not on the host.
_BASE_MISSING = ("Base ref must be a branch", "Base sha can't be blank")

# What `gh pr list` must return for a PullRequest to be built. `reviewDecision`
# and `reviews` are here because `comments` alone misses a normal review
# entirely: it returns issue-level comments only, so a reviewer who leaves
# inline notes and submits CHANGES_REQUESTED registers as silence.
_FIELDS = (
    "number,headRefName,baseRefName,state,isDraft,mergedAt,labels,comments,"
    "statusCheckRollup,reviewDecision,reviews,mergeable"
)
_FAILING = ("FAILURE", "TIMED_OUT")
_CANCELLED = ("CANCELLED",)
_MERGEABLE = {"MERGEABLE": True, "CONFLICTING": False}
# A failed Actions run, and the timestamp prefix its log lines carry.
_RUN_URL = re.compile(r"/actions/runs/(?P<run>\d+)")
_LOG_PREFIX = re.compile(r"^[^\t]*\t[^\t]*\t\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_LOG_CHARS = 6000
# One job of that run, and a bare job log's lines: a timestamp and nothing else.
_JOB_URL = re.compile(r"/job/(?P<job>\d+)")
_JOB_LINE = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_ERROR_LINE = "##[error]"

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
    client: str = "gh"
    # GitHub deletes the head branch on merge, so only the local one is ours.
    deletes_head_branch_on_merge: bool = True
    supports_stacks: bool = True
    # Annotated, not inferred: the Protocol's attribute is read-write, so a
    # narrower literal type would not satisfy it.
    denied_commands: tuple[tuple[str, ...], ...] = (("gh", "pr", "merge"),)
    read_commands: tuple[tuple[str, ...], ...] = (("gh", "pr", "view"), ("gh", "pr", "diff"))
    # `gh pr close` and `gh pr ready` are not denied, so nothing needs an exception.
    permitted_commands: tuple[PermittedCommand, ...] = ()
    requires: tuple[str, ...] = ("slug",)
    ci_name: str = "GitHub Actions"

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

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        """Whether `gh` holds a token for this repo's owner.

        The owner decides which account's token is used, and a call against
        another account's private repo reports it as nonexistent rather than
        forbidden - indistinguishable from a repo with no PRs.
        """
        run = run or (lambda args, **kw: gh(args))
        result = run(
            ["gh", "auth", "token", "--user", repo.account],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode or not result.stdout.strip():
            return f"gh holds no token for {repo.account}"
        return ""

    def access_fix(self, repo: RepoId) -> str:
        return f"gh auth login (as {repo.account})"

    def merge_guard(self, repo: RepoId, *, branch: str, run: Run | None = None) -> str:
        """What stops a merge on the server, or "" when nothing does.

        Branch protection is absent on a free private repo, where the answer
        is honestly "nothing" - which is worth saying out loud, because the
        policy hook is then the only thing between an agent and its own merge.
        """
        argv = ["gh", "api", f"repos/{key(repo)}/branches/{branch}/protection"]
        if run is None:
            found = gh_json(argv, slug=key(repo), default={})
        else:
            result = run(argv, capture_output=True, text=True, check=False)
            try:
                found = json.loads(result.stdout or "{}") if not result.returncode else {}
            except ValueError:
                found = {}
        return "" if found else f"no branch protection on {branch}"

    # --- pull requests --------------------------------------------------------------

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        # `--repo` explicitly: without it gh infers the repo from the working
        # directory's remote, which is right by luck rather than by design, and
        # wrong the moment this is called from anywhere but the worktree.
        found = gh_json(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                key(repo),
                "--head",
                head,
                "--state",
                "all",
                "--json",
                "number",
                "--limit",
                "1",
            ],
            default=[],
        )
        try:
            return int(found[0]["number"]) if isinstance(found, list) and found else None
        except (KeyError, TypeError, ValueError):
            return None

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        try:
            url = gh_out(
                [
                    "gh",
                    "pr",
                    "create",
                    "--repo",
                    key(repo),
                    "--base",
                    base,
                    "--head",
                    head,
                    "--title",
                    title,
                    "--body",
                    body,
                ]
            )
        except GhError as error:
            # The host's words only: the message also holds the title and body.
            if any(text in error.stderr for text in _BASE_MISSING):
                raise BaseMissing(str(error)) from error
            raise
        # gh prints the PR's URL; its last segment is the number.
        return int(url.strip().rstrip("/").rsplit("/", 1)[-1])

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None:
        """Change a PR's base or body, never raising.

        GitHub often retargets a PR on its own when its base branch is deleted
        on merge, but not always, and one left pointing at a deleted branch
        shows a diff containing everything. Doing it explicitly is harmless
        when GitHub already has - and not worth failing a restack over when it
        does not work.
        """
        changes = ["--base", base] if base else []
        changes += ["--body", body] if body else []
        if not changes:
            return
        gh(["gh", "pr", "edit", str(pr), "--repo", key(repo), *changes])

    # --- stacks ---------------------------------------------------------------------

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        found = _stacks_api(repo, "GET", "", ["-F", f"pull_request={pr}"])
        stacks = [_stack(item) for item in found] if isinstance(found, list) else []
        return next((stack for stack in stacks if pr in stack.pulls), None)

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack:
        return _stack(_stacks_api(repo, "POST", "", _pull_fields(pulls)))

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack:
        return _stack(_stacks_api(repo, "POST", f"/{stack}/add", _pull_fields(pulls)))

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str, head: str = ""
    ) -> None:
        """Publish a result as a commit status on the tested SHA.

        Called after the push: GitHub rejects a status for a commit it has not
        seen. 139 characters is GitHub's own limit for the description.
        """
        gh(
            [
                "gh",
                "api",
                "-X",
                "POST",
                f"repos/{key(repo)}/statuses/{sha}",
                "-f",
                f"state={'success' if ok else 'failure'}",
                "-f",
                f"context={context}",
                "-f",
                f"description={description[:139]}",
            ],
            slug=key(repo),
        )

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        raw = gh_out(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                key(repo),
                "--state",
                "all",
                "--limit",
                "100",
                "--json",
                _FIELDS,
            ]
        )
        found = json.loads(raw)
        if not isinstance(found, list):
            raise ValueError("expected a list of pull requests")
        pulls = [self._view(pull) for pull in found]
        return [p for p in pulls if p.head.startswith(head_prefix)] if head_prefix else pulls

    @staticmethod
    def _view(pull: dict) -> PullRequest:
        checks = pull.get("statusCheckRollup") or []
        return PullRequest(
            number=int(pull["number"]),
            head=str(pull.get("headRefName") or ""),
            base=str(pull.get("baseRefName") or ""),
            state=(
                units.MERGED
                if pull.get("mergedAt")
                else units.CLOSED
                if pull.get("state") == "CLOSED"
                else "open"
            ),
            draft=bool(pull.get("isDraft")),
            labels=tuple(sorted(str(label.get("name", "")) for label in pull.get("labels") or [])),
            conversation=tuple(_conversation(pull)),
            comment_bodies=tuple(
                str(item.get("body") or "") for item in pull.get("comments") or []
            ),
            review_decision=(
                "changes_requested" if pull.get("reviewDecision") == "CHANGES_REQUESTED" else ""
            ),
            failing_checks=tuple(
                sorted(
                    str(check.get("name", ""))
                    for check in checks
                    if str(check.get("conclusion", "")).upper() in _FAILING
                )
            ),
            cancelled_checks=tuple(
                sorted(
                    str(check.get("name", ""))
                    for check in checks
                    if str(check.get("conclusion", "")).upper() in _CANCELLED
                )
            ),
            # UNKNOWN is what GitHub says until it has worked the answer out.
            mergeable=_MERGEABLE.get(str(pull.get("mergeable") or "")),
        )

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        slug = key(repo)
        result = gh(
            ["gh", "pr", "view", str(pr), "--repo", slug, "--json", "files",
             "--jq", ".files[].path"]
        )  # fmt: skip
        if result.returncode:
            raise RuntimeError(f"gh pr view {pr} ({slug}): {result.stderr.strip()}")
        return result.stdout.split()

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        """The reviewer's words: review bodies, then inline comments.

        Two requests, made only when a rework is already being dispatched;
        adding them to the poll would cost one per open PR per tick. An inline
        comment whose code has changed comes back with `line: null`, which is
        what `live` records - after a rework that is precisely the comment the
        rework addressed.
        """
        slug = key(repo)

        # The repo is named in the path, not with --repo, so the slug is passed
        # explicitly - otherwise the call runs as whichever account is active.
        def items(kind: str) -> list[dict]:
            found = gh_json(
                ["gh", "api", "--paginate", f"repos/{slug}/pulls/{pr}/{kind}"], slug=slug
            )
            return found if isinstance(found, list) else []

        notes = [
            ReviewNote(id=str(review.get("id", "")), body=str(review.get("body") or ""))
            for review in items("reviews")
        ]
        notes += [
            ReviewNote(
                id=str(comment.get("id", "")),
                body=str(comment.get("body") or ""),
                path=str(comment.get("path", "")),
                line=comment.get("line"),
                live=comment.get("line") is not None,
            )
            for comment in items("comments")
        ]
        return notes

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        """Answer one review comment, and report what the poller will see.

        A reply creates a review of its own with an empty body, which the
        poller would otherwise read as new feedback - so both ids come back to
        be recorded as the pipeline's own.
        """
        slug = key(repo)
        made = gh_json(
            [
                "gh",
                "api",
                "-X",
                "POST",
                f"repos/{slug}/pulls/{pr}/comments/{note_id}/replies",
                "-f",
                f"body={body}",
            ],
            slug=slug,
            default={},
        )
        if not isinstance(made, dict):
            return []
        review = gh_json(
            ["gh", "api", f"repos/{slug}/pulls/{pr}/reviews/{made.get('pull_request_review_id')}"],
            slug=slug,
            default={},
        )
        ids = [str(made.get("node_id", ""))]
        if isinstance(review, dict):
            ids.append(str(review.get("node_id", "")))
        return [i for i in ids if i]

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        slug = key(repo)
        made = gh_json(
            ["gh", "api", "-X", "POST", f"repos/{slug}/issues/{pr}/comments", "-f", f"body={body}"],
            slug=slug,
            default={},
        )
        node = str(made.get("node_id", "")) if isinstance(made, dict) else ""
        return [node] if node else []

    def rerun_checks(self, repo: RepoId, pull: PullRequest) -> None:
        """Re-run the workflow runs behind the cancelled checks, their cancelled
        jobs included."""
        slug = key(repo)
        _, runs = self._runs_with(slug, pull.number, _CANCELLED)
        for run in runs:
            result = gh(["gh", "run", "rerun", run, "--repo", slug, "--failed"], slug=slug)
            if result.returncode:
                raise RuntimeError(f"gh run rerun {run} ({slug}): {result.stderr.strip()}")

    def _runs_with(
        self, slug: str, pr: int, conclusions: Collection[str]
    ) -> tuple[list[dict], list[str]]:
        """The checks of a pull request that ended as one of `conclusions`, and
        the workflow runs they belong to."""
        raw = gh_json(
            ["gh", "pr", "view", str(pr), "--repo", slug, "--json", "statusCheckRollup"],
            default={},
        )
        checks = raw.get("statusCheckRollup") or [] if isinstance(raw, dict) else []
        found = [c for c in checks if str(c.get("conclusion", "")).upper() in conclusions]
        runs = sorted(
            {m["run"] for c in found if (m := _RUN_URL.search(str(c.get("detailsUrl", ""))))}
        )
        return found, runs

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        """The failed CI jobs' logs, for the rework that fixes them.

        "failing checks: <name>" is not enough when the failure is a test tier
        1 never ran, and nothing local can say why.
        """
        if not pull.failing_checks:
            return ""
        slug = key(repo)
        failed, runs = self._runs_with(slug, pull.number, _FAILING)
        names = ", ".join(str(c.get("name")) for c in failed)
        parts = []
        for run in runs:
            result = gh(["gh", "run", "view", run, "--repo", slug, "--log-failed"], slug=slug)
            text = "\n".join(_LOG_PREFIX.sub("", line) for line in result.stdout.splitlines())
            if not text.strip():
                # A run still in progress has no log as a whole, though a job
                # that has finished does: the check fails in a minute and the
                # slowest job takes several, and the poller reports the failure
                # at once. Asked for the run, the rework got an empty block and
                # said so.
                text = self._failed_job_logs(slug, run, failed)
            if not text.strip():
                parts.append(
                    f"CI run {run} ({names}) failed, but its log could not be fetched "
                    "(the run may still be in progress)."
                )
                continue
            parts.append(
                f"CI run {run} ({names}), end of its failed log:\n```\n{text[-_LOG_CHARS:]}\n```"
            )
        return "\n\n".join(parts)

    def _failed_job_logs(self, slug: str, run: str, failed: list[dict]) -> str:
        """The log of each failed job of `run`, up to where the job reported its error.

        A job's whole log ends in the runner's clean-up, so the tail of it says
        nothing; the failure is in the lines before the last `##[error]`.
        """
        out = []
        for check in failed:
            details = str(check.get("detailsUrl", ""))
            match = _JOB_URL.search(details)
            if not match or f"/runs/{run}/" not in details:
                continue
            result = gh(
                [
                    "gh", "api", f"repos/{slug}/actions/jobs/{match['job']}/logs",
                    "--allow-escape-sequences",
                ],
                slug=slug,
            )  # fmt: skip
            lines = [_JOB_LINE.sub("", line) for line in result.stdout.splitlines()]
            errors = [i for i, line in enumerate(lines) if _ERROR_LINE in line]
            if errors:
                lines = lines[: errors[-1] + 1]
            text = "\n".join(lines).strip()
            if text:
                out.append(f"{check.get('name')}:\n{text[-_LOG_CHARS:]}")
        return "\n\n".join(out)

    def _ensure_label(self, slug: str, label: Label) -> None:
        """Make the repo's label what `label` says: created when missing, and
        recoloured or re-described when the repo's copy has drifted, so a
        change to the vocabulary reaches a repo that already has the label."""
        known = gh_json(
            [
                "gh", "label", "list", "--repo", slug,
                "--json", "name,color,description", "--limit", "1000",
            ],
            slug=slug,
        )  # fmt: skip
        # The host matches names without regard to case, so `Running` already
        # there means creating `running` would fail every time.
        wanted = label.name.casefold()
        for item in known:  # type: ignore[union-attr]
            name = str(item.get("name", ""))
            if name.casefold() != wanted:
                continue
            same_colour = str(item.get("color", "")).casefold() == label.color.casefold()
            if not same_colour or (item.get("description") or "") != label.description:
                gh_out(
                    [
                        "gh", "label", "edit", name, "--repo", slug,
                        "--color", label.color, "--description", label.description,
                    ],
                    slug=slug,
                )  # fmt: skip
            return
        gh_out(
            [
                "gh", "label", "create", label.name, "--repo", slug,
                "--color", label.color, "--description", label.description,
            ],
            slug=slug,
        )  # fmt: skip

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        slug = key(repo)
        self._ensure_label(slug, label)
        gh_out(["gh", "pr", "edit", str(pr), "--repo", slug, "--add-label", label.name], slug=slug)

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        slug = key(repo)
        self._ensure_label(slug, label)
        view = gh_out(["gh", "pr", "view", str(pr), "--repo", slug, "--json", "labels"], slug=slug)
        present = {item["name"] for item in json.loads(view or "{}").get("labels", [])}
        argv = ["gh", "pr", "edit", str(pr), "--repo", slug, "--add-label", label.name]
        for name in sorted((present & set(family)) - {label.name}):
            argv += ["--remove-label", name]
        gh_out(argv, slug=slug)

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        slug = key(repo)
        gh_out(["gh", "pr", "edit", str(pr), "--repo", slug, "--remove-label", name], slug=slug)

    def set_draft(self, repo: RepoId, pr: int, draft: bool) -> None:
        raise NotImplementedError

    def close_pr(self, repo: RepoId, pr: int) -> None:
        """Close without merging - a satisfied unit's stale pull request.

        Through `gh_out`, which raises on failure, unlike `update_pr`'s silent
        `gh()`: a close that did not happen must not read as one that did.
        """
        gh_out(["gh", "pr", "close", str(pr), "--repo", key(repo)], slug=key(repo))

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        """Not reached in practice: GitHub deletes the head branch on merge,
        so `deletes_head_branch_on_merge` keeps callers away from this."""
        gh(
            ["gh", "api", "-X", "DELETE", f"repos/{key(repo)}/git/refs/heads/{branch}"],
            slug=key(repo),
        )


FORGE = GitHubForge()

_HTTP_STATUS = re.compile(r"\(HTTP (?P<status>\d{3})\)")


def _pull_fields(pulls: Sequence[int]) -> list[str]:
    # Bottom first: GitHub checks each pull request's base against the head of
    # the one before it.
    return [arg for pull in pulls for arg in ("-F", f"pull_requests[]={pull}")]


def _stacks_api(repo: RepoId, method: str, path: str, fields: list[str]) -> object:
    """One call to the pull request stacks API, or StackRefused saying why not."""
    slug = key(repo)
    try:
        result = gh(["gh", "api", "-X", method, f"repos/{slug}/stacks{path}", *fields], slug=slug)
    except (OSError, subprocess.SubprocessError) as error:
        raise StackRefused(f"could not reach the stacks API: {error}") from error
    if not result.returncode:
        try:
            return json.loads(result.stdout or "null")
        except ValueError as error:
            raise StackRefused(
                f"unreadable answer from the stacks API: {result.stdout!r:.200}"
            ) from error
    match = _HTTP_STATUS.search(result.stderr)
    status = match["status"] if match else ""
    try:
        body = json.loads(result.stdout or "{}")
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    details = [str(e.get("message", "")) for e in body.get("errors") or [] if isinstance(e, dict)]
    message = "; ".join(part for part in [str(body.get("message") or ""), *details] if part)
    reason = f"HTTP {status}: {message}" if status else message or result.stderr.strip()
    # 409: another request is changing the same stack right now.
    raise StackRefused(reason, concurrent=status == "409")


def _stack(found: object) -> Stack:
    # Any answer not shaped like a stack is a refusal, not a crash: the step
    # that asks has already opened the pull request, and must not fail it.
    unexpected = StackRefused(f"unexpected answer from the stacks API: {found!r:.200}")
    if not isinstance(found, dict):
        raise unexpected
    try:
        return Stack(
            number=int(found["number"]),
            open=bool(found.get("open")),
            pulls=tuple(int(pull["number"]) for pull in found.get("pull_requests") or []),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise unexpected from error


def _conversation(pull: dict) -> list[str]:
    """Every comment and submitted review on the PR, by id.

    Not a PENDING review: that is a draft the reviewer has not submitted.
    GitHub shows it to its own author, and the repo is read as its owner - so a
    review still being written would count as new and send the unit back for
    rework with nothing to act on.
    """
    ids = [str(item["id"]) for item in (pull.get("comments") or []) if item.get("id")]
    ids += [
        str(item["id"])
        for item in (pull.get("reviews") or [])
        if item.get("id") and item.get("state") != "PENDING"
    ]
    return ids
