"""The Azure DevOps forge: identity and access, which is all of it so far.

The rest of the host — opening a PR, polling it, answering review — raises
rather than pretending, so a unit in such a repo is held instead of failed
(`cli/pipeline._build`, and the `node_npm` profile before it). What is here is
what `abk init` and `abk doctor` need to stop being wrong about the repo.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.config import AzureDevOpsConfig, RepoConfig
from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.pipeline.units import CLOSED, MERGED
from tests.forges import azure_answers

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


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
    """`implemented = False` is what `cli/pipeline._build` turns into `held`.

    It stays False while the review round-trip is missing, even though the
    pull request lifecycle works: a unit whose reviewer is never heard would
    sit in review forever, which is worse than being held and said so."""
    assert FORGE.implemented is False
    with pytest.raises(NotImplementedError) as refused:
        FORGE.review_notes(REPO, 41)

    assert "review_notes" in str(refused.value)


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


# --- the pull request lifecycle ---------------------------------------------------


def answering(payload: object, *, calls: list[list[str]] | None = None):
    """An `az` stand-in that records argv and answers with `payload`."""

    def run(args, **kwargs):
        if calls is not None:
            calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    return run


def view(document: dict) -> PullRequest:
    [pull] = FORGE.list_prs(REPO, run=answering([document]))
    return pull


def test_only_a_completed_status_means_merged() -> None:
    """The field the pipeline must not get wrong. An open pull request carries
    `mergeStatus: succeeded` and a populated `lastMergeCommit` exactly as a
    merged one does — reading either as proof of a merge marks every open PR
    merged, which restacks its children and deletes their branches."""
    assert azure_answers.OPEN["mergeStatus"] == azure_answers.COMPLETED["mergeStatus"]
    assert bool(azure_answers.OPEN["lastMergeCommit"])

    assert view(azure_answers.OPEN).state == "open"
    assert view(azure_answers.COMPLETED).state == MERGED
    assert view(azure_answers.ABANDONED).state == CLOSED


def test_branch_names_lose_their_ref_prefix() -> None:
    """Azure reports `refs/heads/x`; every caller here works in branch names,
    and a base of `refs/heads/main` would be pushed to as a branch of that
    name."""
    pull = view(azure_answers.OPEN)

    assert (pull.head, pull.base) == ("spec/add-marker/1", "main")


def test_a_pull_request_with_no_labels_is_not_an_error() -> None:
    """Azure sends `null`, not `[]`."""
    assert view(azure_answers.OPEN).labels == ()
    assert view(azure_answers.pull(labels=[{"name": "agent:hold"}])).labels == ("agent:hold",)


def test_a_rejecting_reviewer_asks_for_rework() -> None:
    document = azure_answers.pull(reviewers=[azure_answers.reviewer(-10)])

    assert view(document).review_decision == "changes_requested"


def test_waiting_for_the_author_also_asks_for_rework() -> None:
    """-5 is "waiting for author": the reviewer has asked for something."""
    document = azure_answers.pull(reviewers=[azure_answers.reviewer(-5)])

    assert view(document).review_decision == "changes_requested"


def test_approved_with_suggestions_is_not_rework() -> None:
    """Vote 5 approves. Read as rework it would send an approved unit back
    round the loop, every poll, for as long as the vote stands."""
    document = azure_answers.pull(reviewers=[azure_answers.reviewer(5)])

    assert view(document).review_decision == ""
    assert view(azure_answers.pull(reviewers=[azure_answers.reviewer(10)])).review_decision == ""


def test_a_group_s_vote_is_not_a_person_s() -> None:
    """A required-reviewers group carries `isContainer` and votes on behalf of
    nobody; its standing -5 would rework the unit forever."""
    document = azure_answers.pull(reviewers=[azure_answers.reviewer(-5, container=True)])

    assert view(document).review_decision == ""


def test_listing_names_the_project_and_repository() -> None:
    calls: list[list[str]] = []

    FORGE.list_prs(REPO, run=answering([azure_answers.OPEN], calls=calls))

    args = calls[0]
    assert args[:4] == ["az", "repos", "pr", "list"]
    assert args[args.index("--project") + 1] == "Some Project"
    assert args[args.index("--repository") + 1] == "Some Repo"
    assert args[args.index("--status") + 1] == "all", "a merged PR is what the poller waits for"


def test_listing_can_be_narrowed_to_the_pipeline_s_own_branches() -> None:
    mine = azure_answers.pull(sourceRefName="refs/heads/spec/add-marker/1")
    theirs = azure_answers.pull(pullRequestId=99, sourceRefName="refs/heads/fix/by-hand")

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, json.dumps([mine, theirs]), "")

    found = FORGE.list_prs(REPO, head_prefix="spec/", run=run)

    assert [pull.number for pull in found] == [162]


def test_creating_a_pr_reports_the_id_azure_returned() -> None:
    """No URL parsing, unlike `gh pr create`: the id is in the answer."""
    calls: list[list[str]] = []
    run = answering({"pullRequestId": 41}, calls=calls)

    number = FORGE.create_pr(REPO, head="spec/x/1", base="main", title="t", body="b", run=run)

    assert number == 41
    args = calls[0]
    assert args[args.index("--source-branch") + 1] == "spec/x/1"
    assert args[args.index("--target-branch") + 1] == "main"
    assert args[args.index("--description") + 1] == "b"


def test_finding_a_pr_by_its_branch() -> None:
    calls: list[list[str]] = []

    number = FORGE.find_pr(
        REPO, head="spec/x/1", run=answering([{"pullRequestId": 41}], calls=calls)
    )

    assert number == 41
    assert calls[0][calls[0].index("--source-branch") + 1] == "spec/x/1"


def test_a_branch_with_no_pull_request_yet() -> None:
    assert FORGE.find_pr(REPO, head="spec/x/1", run=answering([])) is None


def test_retargeting_goes_through_the_rest_api(tmp_path: Path) -> None:
    """`az repos pr update` has no `--target-branch`, so the base can only be
    changed by a PATCH — and a PR left pointing at a branch that merged away
    shows a diff containing everything."""
    calls: list[list[str]] = []
    sent: list[object] = []

    def run(args, **kwargs):
        calls.append(args)
        sent.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return subprocess.CompletedProcess(args, 0, "{}", "")

    FORGE.update_pr(REPO, 41, base="main", run=run)

    [args] = calls
    assert args[:3] == ["az", "devops", "invoke"]
    assert args[args.index("--http-method") + 1] == "PATCH"
    assert sent == [{"targetRefName": "refs/heads/main"}], "the API wants the full ref"


def test_updating_only_the_body_uses_the_plain_command() -> None:
    calls: list[list[str]] = []

    FORGE.update_pr(REPO, 41, body="new", run=answering({"pullRequestId": 41}, calls=calls))

    [args] = calls
    assert args[:4] == ["az", "repos", "pr", "update"]
    assert args[args.index("--description") + 1] == "new"


def test_an_update_with_nothing_to_change_makes_no_call() -> None:
    calls: list[list[str]] = []

    FORGE.update_pr(REPO, 41, run=answering({}, calls=calls))

    assert calls == []


def test_the_source_branch_is_ours_to_delete() -> None:
    """Azure keeps the source branch unless the PR asked for it to go, so
    unlike GitHub the remote branch is left behind after a merge."""
    assert FORGE.deletes_head_branch_on_merge is False


def test_deleting_a_branch_looks_up_the_commit_it_points_at() -> None:
    """Azure refuses a ref delete that does not name the commit being removed
    — a guard against deleting a branch that moved since it was read."""
    calls: list[list[str]] = []

    def run(args, **kwargs):
        calls.append(args)
        listing = [{"name": "refs/heads/spec/x/1", "objectId": "abc123"}]
        return subprocess.CompletedProcess(args, 0, json.dumps(listing), "")

    FORGE.delete_remote_branch(REPO, "spec/x/1", run=run)

    lookup, delete = calls
    assert lookup[:3] == ["az", "repos", "ref"] and lookup[3] == "list"
    assert delete[3] == "delete"
    assert delete[delete.index("--name") + 1] == "heads/spec/x/1"
    assert delete[delete.index("--object-id") + 1] == "abc123"


def test_a_branch_already_gone_is_not_an_error() -> None:
    """The remote may have been cleaned up by hand, or by the merge itself."""

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "[]", "")

    FORGE.delete_remote_branch(REPO, "spec/x/1", run=run)
