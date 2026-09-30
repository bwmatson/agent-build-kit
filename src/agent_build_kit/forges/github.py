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
from typing import TYPE_CHECKING

from agent_build_kit.forges.base import PullRequest, RepoId, ReviewNote, Run, key
from agent_build_kit.pipeline import units
from agent_build_kit.pipeline.shell import gh, gh_json, gh_out

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

# What `gh pr list` must return for a PullRequest to be built. `reviewDecision`
# and `reviews` are here because `comments` alone misses a normal review
# entirely: it returns issue-level comments only, so a reviewer who leaves
# inline notes and submits CHANGES_REQUESTED registers as silence.
_FIELDS = (
    "number,headRefName,baseRefName,state,isDraft,mergedAt,labels,comments,"
    "statusCheckRollup,reviewDecision,reviews"
)
_FAILING = ("FAILURE", "TIMED_OUT", "CANCELLED")
# A failed Actions run, and the timestamp prefix its log lines carry.
_RUN_URL = re.compile(r"/actions/runs/(?P<run>\d+)")
_LOG_PREFIX = re.compile(r"^[^\t]*\t[^\t]*\t\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_LOG_CHARS = 6000

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
    # GitHub deletes the head branch on merge, so only the local one is ours.
    deletes_head_branch_on_merge: bool = True
    # Annotated, not inferred: the Protocol's attribute is read-write, so a
    # narrower literal type would not satisfy it.
    denied_commands: tuple[tuple[str, ...], ...] = (("gh", "pr", "merge"),)
    requires: tuple[str, ...] = ("slug",)

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

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str
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

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        """The failed CI jobs' logs, for the rework that fixes them.

        "failing checks: <name>" is not enough when the failure is a test tier
        1 never ran, and nothing local can say why.
        """
        if not pull.failing_checks:
            return ""
        slug = key(repo)
        raw = gh_json(
            ["gh", "pr", "view", str(pull.number), "--repo", slug, "--json", "statusCheckRollup"],
            default={},
        )
        checks = raw.get("statusCheckRollup") or [] if isinstance(raw, dict) else []
        failed = [c for c in checks if str(c.get("conclusion", "")).upper() in _FAILING]
        runs = sorted(
            {m["run"] for c in failed if (m := _RUN_URL.search(str(c.get("detailsUrl", ""))))}
        )
        names = ", ".join(str(c.get("name")) for c in failed)
        parts = []
        for run in runs:
            result = gh(["gh", "run", "view", run, "--repo", slug, "--log-failed"], slug=slug)
            text = "\n".join(_LOG_PREFIX.sub("", line) for line in result.stdout.splitlines())
            parts.append(
                f"CI run {run} ({names}), end of its failed log:\n```\n{text[-_LOG_CHARS:]}\n```"
            )
        return "\n\n".join(parts)

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        """Not reached in practice: GitHub deletes the head branch on merge,
        so `deletes_head_branch_on_merge` keeps callers away from this."""
        gh(
            ["gh", "api", "-X", "DELETE", f"repos/{key(repo)}/git/refs/heads/{branch}"],
            slug=key(repo),
        )


FORGE = GitHubForge()


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
