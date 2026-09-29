"""The Azure DevOps forge: identity and access, which is all of it so far.

The rest of the host — opening a PR, polling it, answering review — raises
rather than pretending, so a unit in such a repo is held instead of failed
(`cli/pipeline._build`, and the `node_npm` profile before it). What is here is
what `abk init` and `abk doctor` need to stop being wrong about the repo.
"""

from __future__ import annotations

import subprocess

import pytest

from agent_build_kit import forges
from agent_build_kit.config import AzureDevOpsConfig, RepoConfig
from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import RepoId


@pytest.mark.parametrize(
    "url",
    [
        "git@ssh.dev.azure.com:v3/acme/Some%20Project/Some%20Repo",
        "ssh://git@ssh.dev.azure.com:v3/acme/Some%20Project/Some%20Repo",
        "https://acme@dev.azure.com/acme/Some%20Project/_git/Some%20Repo",
        "https://dev.azure.com/acme/Some%20Project/_git/Some%20Repo",
    ],
)
def test_every_origin_form_yields_the_same_decoded_identity(url: str) -> None:
    """Decoded: an Azure remote percent-encodes a project with a space in it,
    and every API and CLI call wants the readable form back. `%20` sent to
    `az repos --project` names a project that does not exist."""
    repo = FORGE.parse_remote(url)

    assert repo is not None
    assert (repo.forge, repo.account, repo.project, repo.name) == (
        "azure_devops",
        "acme",
        "Some Project",
        "Some Repo",
    )


def test_a_github_remote_is_not_claimed() -> None:
    """Both forges see every remote, so each has to refuse the other's."""
    assert FORGE.parse_remote("git@github.com:example/app.git") is None
    assert FORGE.parse_remote("") is None


def test_the_registry_asks_the_host_anchored_forge_first() -> None:
    """GitHub's pattern accepts any `alias:owner/name`, so asked first it
    would claim this remote and name the repo `v3/acme`."""
    repo = forges.identify("git@ssh.dev.azure.com:v3/acme/Some%20Project/Some%20Repo")

    assert repo is not None
    assert repo.forge == "azure_devops"
    assert repo.project == "Some Project"


def test_the_identity_key_carries_all_three_segments() -> None:
    """Two repos in one organisation can share a name across projects, so the
    project has to be in the key the state files are written under."""
    repo = FORGE.parse_remote("https://dev.azure.com/acme/Some%20Project/_git/Some%20Repo")

    assert repo is not None
    assert forges.key(repo) == "acme/Some Project/Some Repo"


def test_the_identity_comes_from_its_own_block_in_abk_yaml() -> None:
    """Not from `slug`: three segments re-split from one string is exactly the
    ambiguity a project name containing a slash would break."""
    config = RepoConfig(
        path="app",
        forge="azure_devops",
        azure_devops=AzureDevOpsConfig(org="acme", project="Some Project", repo="Some Repo"),
    )

    assert FORGE.identity(config) == RepoId(
        forge="azure_devops", account="acme", project="Some Project", name="Some Repo"
    )


def test_the_web_url_points_at_the_pull_request() -> None:
    repo = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

    assert FORGE.web_url(repo) == "https://dev.azure.com/acme/Some%20Project/_git/Some%20Repo"
    assert FORGE.web_url(repo, pr=7).endswith("/pullrequest/7")


def test_access_is_proved_by_reading_the_repo_itself() -> None:
    """Not `az account show`: only a read of the named repo proves the
    credential *and* the access, which is what the check is for."""
    calls: list[list[str]] = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"id": "abc"}', "")

    repo = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

    assert FORGE.check_access(repo, run=run) == ""
    assert calls[0][:3] == ["az", "repos", "show"]
    assert "Some Project" in calls[0], "decoded, and named rather than defaulted"


def test_a_repo_that_cannot_be_read_says_so() -> None:
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "TF400813: not authorized")

    repo = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

    reason = FORGE.check_access(repo, run=run)

    assert "Some Repo" in reason
    assert "az login" in FORGE.access_fix(repo) or "PAT" in FORGE.access_fix(repo)


def test_nothing_on_the_server_stops_a_merge_without_a_policy() -> None:
    """Worth saying out loud rather than merely being true: with no branch
    policy, the command hook is the only thing between an agent and its own
    merge."""
    repo = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "[]", "")

    assert "main" in FORGE.merge_guard(repo, branch="main", run=run)


def test_the_unfinished_half_holds_a_unit_rather_than_failing_it() -> None:
    """`implemented = False` is what `cli/pipeline._build` turns into `held`."""
    repo = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

    assert FORGE.implemented is False
    with pytest.raises(NotImplementedError) as refused:
        FORGE.create_pr(repo, head="spec/x/1", base="main", title="t", body="b")

    assert "create_pr" in str(refused.value)


def test_every_way_of_merging_is_denied_to_the_agent() -> None:
    """Wider than GitHub's one command: an update can complete a PR, a vote
    can approve one, and both `az rest` and `az devops invoke` reach the same
    API directly."""
    denied = {" ".join(command) for command in FORGE.denied_commands}

    assert "az repos pr update" in denied
    assert "az repos pr set-vote" in denied
    assert "az repos policy" in denied
    assert "az rest" in denied
    assert "az devops invoke" in denied
