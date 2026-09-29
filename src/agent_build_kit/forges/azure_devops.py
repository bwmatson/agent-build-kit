"""Azure DevOps as a code host.

Identity and access are real; the pull request lifecycle is not yet, so
`implemented` is False and the rest raises through `_todo`. A unit in such a
repo is held rather than failed — `cli/pipeline._build` turns
`NotImplementedError` into `held`, as it already does for the `node_npm`
toolchain profile.

Two things about this host shape everything below:

**Three segments, decoded.** A repo is organisation / project / repo, and the
remote percent-encodes any of them containing a space. `%20` handed to
`az repos --project` names a project that does not exist, so the identity is
decoded once, here, and every caller gets the readable form.

**Merging has a wide surface.** GitHub has one command; here a PR is completed
by `az repos pr update --status completed`, approved by `az repos pr set-vote`,
unblocked by `az repos policy`, and all of it is reachable through `az rest`
and `az devops invoke`. `denied_commands` names every one of them, and the
registry's union means they are refused in a GitHub checkout too.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

from agent_build_kit.forges.base import PullRequest, RepoId, ReviewNote, Run
from agent_build_kit.pipeline import az

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

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


class AzureDevOpsForge:
    name: str = "azure_devops"
    # Identity and access only, so far. See the module docstring.
    implemented: bool = False
    # Azure DevOps keeps the source branch unless the PR asked for it to go,
    # so the remote branch is ours to delete.
    deletes_head_branch_on_merge: bool = False
    # Annotated, not inferred: the Protocol's attribute is read-write, so a
    # narrower literal type would not satisfy it.
    denied_commands: tuple[tuple[str, ...], ...] = (
        # Denied whole rather than by flag: `--status completed`,
        # `--auto-complete` and `--bypass-policy` all merge, and its only
        # innocent uses are the title and description, which the pipeline sets
        # itself.
        ("az", "repos", "pr", "update"),
        ("az", "repos", "pr", "set-vote"),
        ("az", "repos", "policy"),
        # The raw escapes, which reach all of the above.
        ("az", "rest"),
        ("az", "devops", "invoke"),
    )
    requires: tuple[str, ...] = ("azure_devops.org", "azure_devops.project", "azure_devops.repo")

    def _todo(self, what: str):
        raise NotImplementedError(
            f"the {self.name} forge is not implemented in this release ({what})"
        )

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

    # --- the rest, once the lifecycle lands -----------------------------------------

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        return self._todo("find_pr")

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        return self._todo("create_pr")

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None:
        return self._todo("update_pr")

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        return self._todo("list_prs")

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        return self._todo("pr_files")

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        return self._todo("review_notes")

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        return self._todo("post_reply")

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        return self._todo("post_comment")

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str
    ) -> None:
        return self._todo("post_status")

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        return self._todo("failed_check_logs")

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        return self._todo("delete_remote_branch")


FORGE = AzureDevOpsForge()
