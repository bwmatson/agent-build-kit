"""The Azure DevOps forge.

The fixtures these run against were recorded from real pull requests and kept
whole, because the mistakes this host invites are all mistakes about fields
that look decisive and are not: a successful merge status on an open PR, a
comment the server wrote itself, a reviewer's vote that approves.
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
from agent_build_kit.pipeline import az
from agent_build_kit.pipeline.az import AzError
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
    assert view(azure_answers.pull(labels=[{"name": "agent-hold"}])).labels == ("agent-hold",)


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


def test_retargeting_goes_through_the_rest_api() -> None:
    """Twice unreachable through the CLI: `az repos pr update` has no
    `--target-branch`, and `az devops invoke` resolves `git/pullRequests` to
    the organisation-level location, which answers GET and refuses PATCH. A PR
    left pointing at a branch that merged away shows a diff of everything."""
    seen: list = []

    def open_url(request, timeout=None):
        seen.append(request)
        if request.get_method() == "GET":
            return _Answer(json.dumps({"targetRefName": "refs/heads/dev"}))
        return _Answer("{}")

    def token(args, **kwargs):
        """`az account get-access-token ... -o tsv` prints the token bare."""
        return subprocess.CompletedProcess(args, 0, "a-token\n", "")

    # `run` as well as `open_url`: without it the call falls through to a real
    # `az account get-access-token`, which passes on a machine that happens to
    # be signed in and fails everywhere else.
    FORGE.update_pr(REPO, 41, base="main", run=token, open_url=open_url)

    request = seen[-1]
    assert request.get_method() == "PATCH"
    assert json.loads(request.data.decode()) == {"targetRefName": "refs/heads/main"}
    assert "/AI%20Accelerators" not in request.full_url, "this repo names no installation"
    assert request.full_url.endswith("/pullRequests/41?api-version=7.1")
    assert "/Some%20Project/_apis/git/repositories/Some%20Repo" in request.full_url
    assert request.get_header("Authorization") == "Bearer a-token"


def test_a_pull_request_already_on_the_branch_is_not_retargeted() -> None:
    """Azure refuses it with a 400, "This pull request already targets ...", and
    the push step retargets on every rework of a PR it already opened."""
    seen: list = []

    def open_url(request, timeout=None):
        seen.append(request.get_method())
        return _Answer(json.dumps({"targetRefName": "refs/heads/dev"}))

    def token(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "a-token\n", "")

    FORGE.update_pr(REPO, 41, base="dev", run=token, open_url=open_url)

    assert seen == ["GET"], "read, found it already there, wrote nothing"


def test_a_refusal_from_azure_says_what_azure_said() -> None:
    import io
    import urllib.error

    body = json.dumps({"message": "This pull request already targets refs/heads/dev"})

    def open_url(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            {},
            io.BytesIO(body.encode()),  # type: ignore[arg-type]
        )

    def token(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "a-token\n", "")

    with pytest.raises(az.AzError) as raised:
        az.rest(
            "PATCH", "https://dev.azure.com/o/p/_apis/x", payload={}, run=token, open_url=open_url
        )

    assert "400 Bad Request" in str(raised.value)
    assert "already targets refs/heads/dev" in str(raised.value)
    assert raised.value.stderr == "This pull request already targets refs/heads/dev"


def test_closing_abandons_through_the_cli_with_a_shape_the_deny_list_accepts() -> None:
    """The pipeline's own argv and the exception list cannot drift apart: the
    command `close_pr` runs is one `forges.denies` lets through."""
    calls: list[list[str]] = []

    FORGE.close_pr(REPO, 41, run=answering({}, calls=calls))

    [argv] = calls
    assert argv[:4] == ["az", "repos", "pr", "update"]
    assert argv[argv.index("--id") + 1] == "41"
    assert argv[argv.index("--status") + 1] == "abandoned"
    assert forges.denies(argv) == ""


def test_a_close_that_fails_raises() -> None:
    """The caller records the failure and leaves the unit satisfied either
    way, but it has to be told the close did not happen."""

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "TF401019: not found")

    with pytest.raises(AzError):
        FORGE.close_pr(REPO, 41, run=run)


@pytest.mark.parametrize(
    "command",
    [
        "az repos pr update --id 5 --status abandoned",
        "az repos pr update --id=5 --status=abandoned",
        "az repos pr update --id 5 --status active",
        "az repos pr update --id 5 --status=active",
        "az repos pr update --id 5 --draft true",
        "az repos pr update --id 5 --draft false",
        "az repos pr update --id=5 --draft=true",
        "az repos pr update --id=5 --draft=false",
        "az repos pr update --id 5 --status abandoned --org https://dev.azure.com/acme",
        "az repos pr update --id 5 --status abandoned --organization=x --detect true",
    ],
)
def test_the_permitted_update_shapes_are_allowed(command: str) -> None:
    assert forges.denies(command.split()) == ""


@pytest.mark.parametrize(
    "command",
    [
        "az repos pr update --id 5 --status completed",
        "az repos pr update --id 5 --status abandoned --auto-complete true",
        "az repos pr update --id 5 --status abandoned --bypass-policy true",
        "az repos pr update --id 5 --status abandoned --squash true",
        "az repos pr update --id 5 --status abandoned --delete-source-branch true",
        "az repos pr update --id 5 --status abandoned --merge-commit-message x",
        "az repos pr update --id 5 --title x",
        "az repos pr update --id 5 --stat abandoned",
        "az repos pr update --id 5 --status abandoned --auto-c true",
        "az repos pr update --id 5 --description x",
        "az repos pr update --id five --status abandoned",
        "az repos pr update --id 5 --status abandoned --status active",
        "az repos pr update --id 5 --status",
        "az repos pr update --id 5 --status --draft true",
        "az repos pr update --id 5 --status abandoned extra",
        "az repos pr update --id 5 --draft maybe",
        "az repos pr set-vote --id 5 --vote approve",
        "az repos policy create",
        "az rest --method patch --url https://x --body {status:abandoned}",
        "az devops invoke --area git --resource pullRequests",
    ],
)
def test_anything_else_under_a_denied_prefix_stays_denied(command: str) -> None:
    assert forges.denies(command.split()), command


class _Answer:
    """The little of a urlopen answer that `az.rest` reads."""

    def __init__(self, body: str) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


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


# --- the review round-trip --------------------------------------------------------


def notes(*items: dict, calls: list[list[str]] | None = None) -> list:
    return FORGE.review_notes(REPO, 41, run=answering(azure_answers.threads(*items), calls=calls))


def test_the_server_s_own_comments_are_not_review() -> None:
    """The trap this host has and GitHub does not. Azure writes "the reference
    was updated" on the thread list on *every push*, and the pipeline pushes on
    every rework and every restack — so counted as a comment, each push reworks
    the unit that just pushed, forever."""
    found = notes(azure_answers.SYSTEM_PUSH, azure_answers.SYSTEM_REVIEWER_ADDED)

    assert found == []


def test_a_comment_with_no_type_is_still_a_comment() -> None:
    """`commentType` is null on real comments, so the rule is "skip system",
    not "keep text" — inverted, it drops a reviewer's words."""
    [bodies] = [[note.body for note in notes(azure_answers.REVIEW_THREAD)]]

    assert "Addressed in a1b2c3d." in bodies


def test_a_note_carries_its_thread_and_its_file() -> None:
    found = notes(azure_answers.REVIEW_THREAD)

    first = found[0]
    assert first.id == "478.1", "comment ids restart per thread, so the thread's is part of it"
    assert first.path == "poc/validate/effective_schema.py", "no leading slash"
    assert first.line == 14


def test_a_resolved_thread_is_not_replayed_to_the_next_rework() -> None:
    """Nothing here goes stale on its own, the way GitHub reports `line: null`
    once the code moves. A thread the reviewer resolved is the signal."""
    assert all(not note.live for note in notes(azure_answers.REVIEW_THREAD))
    assert all(note.live for note in notes(azure_answers.thread(status="active")))


def test_the_threads_are_read_through_the_rest_api() -> None:
    calls: list[list[str]] = []

    notes(azure_answers.REVIEW_THREAD, calls=calls)

    [args] = calls
    assert args[:3] == ["az", "devops", "invoke"]
    assert args[args.index("--resource") + 1] == "pullRequestThreads"
    assert "pullRequestId=41" in args


def test_a_reply_lands_in_the_thread_it_answers() -> None:
    calls: list[list[str]] = []
    sent: list[object] = []

    def run(args, **kwargs):
        calls.append(args)
        if "--in-file" in args:
            sent.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return subprocess.CompletedProcess(args, 0, json.dumps({"id": 4}), "")

    ids = FORGE.post_reply(REPO, 41, note_id="478.1", body="Now a frozen model.", run=run)

    assert ids == ["478.4"], "what the next poll will see in the conversation"
    assert "threadId=478" in calls[0]
    assert sent == [{"content": "Now a frozen model.", "parentCommentId": 1, "commentType": 1}]


def test_a_summary_opens_a_thread_of_its_own() -> None:
    """Not anchored to a line: a rework's summary answers the review, not one
    note in it."""
    sent: list[dict] = []

    def run(args, **kwargs):
        if "--in-file" in args:
            sent.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"id": 480, "comments": [{"id": 1}]}), ""
        )

    ids = FORGE.post_comment(REPO, 41, body="Also dropped the /mcp key.", run=run)

    assert ids == ["480.1"]
    [opened] = sent
    assert opened["comments"][0]["content"] == "Also dropped the /mcp key."
    assert opened["status"] == "active"


def test_a_polled_pull_request_carries_its_conversation() -> None:
    """What the poller diffs on. Without the ids there is no "new comment" to
    notice, and a reviewer would go unheard."""
    listing = [azure_answers.OPEN]
    replies = azure_answers.threads(azure_answers.REVIEW_THREAD, azure_answers.SYSTEM_PUSH)

    def run(args, **kwargs):
        payload = replies if "pullRequestThreads" in args else listing
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    [pull] = FORGE.list_prs(REPO, run=run)

    assert pull.conversation == ("478.1", "478.2", "478.3"), "the server's own are not in it"
    assert pull.comment_bodies[0] == "The declared schema does not match what extraction stores."


# --- statuses and changed files ---------------------------------------------------


def test_a_status_is_posted_against_the_commit_that_was_tested() -> None:
    """Tier 2 gates the push, and its result belongs to one commit: a restack
    changes the SHA, and a status on the wrong commit is worse than none."""
    calls: list[list[str]] = []
    sent: list[dict] = []

    def run(args, **kwargs):
        calls.append(args)
        if "--in-file" in args:
            sent.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return subprocess.CompletedProcess(args, 0, json.dumps({"id": 1}), "")

    FORGE.post_status(
        REPO, sha="abc123", ok=True, context="local/tier2", description="4 passed", run=run
    )

    assert "commitId=abc123" in calls[0]
    [posted] = sent
    assert posted["state"] == "succeeded"
    assert posted["context"] == {"genre": "local", "name": "tier2"}
    assert posted["description"] == "4 passed"


def test_a_failing_run_posts_a_failing_state() -> None:
    sent: list[dict] = []

    def run(args, **kwargs):
        if "--in-file" in args:
            sent.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return subprocess.CompletedProcess(args, 0, json.dumps({"id": 1}), "")

    FORGE.post_status(
        REPO, sha="abc123", ok=False, context="local/tier2", description="1 failed", run=run
    )

    assert sent[0]["state"] == "failed"


def test_a_long_description_is_truncated_by_the_forge() -> None:
    """Every host has its own limit, and a caller has no business knowing
    them — an over-long description loses the whole status, not its tail."""
    sent: list[dict] = []

    def run(args, **kwargs):
        if "--in-file" in args:
            sent.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return subprocess.CompletedProcess(args, 0, json.dumps({"id": 1}), "")

    FORGE.post_status(
        REPO, sha="abc", ok=True, context="local/tier2", description="x" * 2000, run=run
    )

    assert len(sent[0]["description"]) < 1000


def test_a_context_with_no_genre_still_posts() -> None:
    sent: list[dict] = []

    def run(args, **kwargs):
        if "--in-file" in args:
            sent.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return subprocess.CompletedProcess(args, 0, json.dumps({"id": 1}), "")

    FORGE.post_status(REPO, sha="abc", ok=True, context="tier2", description="d", run=run)

    assert sent[0]["context"] == {"genre": "abk", "name": "tier2"}


def test_only_a_failed_or_errored_check_counts_as_failing() -> None:
    """A check still running is waiting, not failing: read as a failure it
    would send the unit back for rework while its build was in progress."""
    listing = [azure_answers.OPEN]
    statuses = {
        "value": [
            azure_answers.FAILED_STATUS,
            azure_answers.PASSED_STATUS,
            azure_answers.PENDING_STATUS,
        ]
    }

    def run(args, **kwargs):
        payload: object = listing
        if "pullRequestThreads" in args:
            payload = azure_answers.threads()
        elif "pullRequestStatuses" in args:
            payload = statuses
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    [pull] = FORGE.list_prs(REPO, run=run)

    assert pull.failing_checks == ("continuous-integration/build",)


def test_the_check_report_says_what_failed_and_where_to_look() -> None:
    """No build log is fetched: what a status carries is its description and a
    link, and inventing a log fetch for a build this host may not even be
    running would be a guess in the rework's prompt."""
    pull = PullRequest(
        number=41,
        head="spec/x/1",
        base="main",
        state="open",
        failing_checks=("continuous-integration/build",),
    )
    statuses = {"value": [azure_answers.FAILED_STATUS, azure_answers.PASSED_STATUS]}

    report = FORGE.failed_check_logs(REPO, pull, run=answering(statuses))

    assert "CI build failed" in report
    assert "buildId=1" in report
    assert "CI build succeeded" not in report


def test_a_pull_request_with_no_failing_checks_reports_nothing() -> None:
    pull = PullRequest(number=41, head="spec/x/1", base="main", state="open")

    assert FORGE.failed_check_logs(REPO, pull, run=answering({"value": []})) == ""


def test_the_changed_files_come_from_the_newest_iteration() -> None:
    """Each push makes an iteration, and what the change touched is what the
    newest one holds."""
    calls: list[list[str]] = []

    def run(args, **kwargs):
        calls.append(args)
        payload = (
            azure_answers.ITERATIONS if "pullRequestIterations" in args else azure_answers.CHANGES
        )
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    files = FORGE.pr_files(REPO, 41, run=run)

    assert files == ["poc/validate/params.py", "poc/validate/verdict.py"], "no folders, no slash"
    assert "iterationId=5" in calls[1], "the newest iteration, not the first"


def test_the_forge_is_now_complete() -> None:
    """Every method answers, so units in an Azure DevOps repo build rather
    than being held."""
    assert FORGE.implemented is True


@pytest.mark.parametrize(
    "stderr",
    [
        "ERROR: TF401028: The reference 'refs/heads/spec/x/0' does not exist. "
        "Check the name and try again.",
        "ERROR: TF401398: The pull request cannot be activated because the source "
        "and/or the target branch no longer exists, or the object id is not valid.",
    ],
)
def test_a_pr_refused_for_a_missing_base_is_its_own_error(stderr: str) -> None:
    from agent_build_kit.forges.base import BaseMissing

    def refuse(message: str):
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, "", message)

        return run

    with pytest.raises(BaseMissing):
        FORGE.create_pr(
            REPO, head="spec/x/1", base="spec/x/0", title="t", body="b", run=refuse(stderr)
        )

    duplicate = "ERROR: TF401179: An active pull request for the source and target already exists."
    with pytest.raises(AzError) as refused:
        FORGE.create_pr(
            REPO, head="spec/x/1", base="main", title="t", body="b", run=refuse(duplicate)
        )
    assert not isinstance(refused.value, BaseMissing)


def test_a_body_quoting_a_missing_base_code_does_not_make_another_refusal_one() -> None:
    """The error message holds the command line, title and description
    included; only what the host said decides whether the base is missing."""
    from agent_build_kit.forges.base import BaseMissing

    def run(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 1, "", "ERROR: TF401179: An active pull request already exists."
        )

    with pytest.raises(AzError) as refused:
        FORGE.create_pr(
            REPO,
            head="spec/x/1",
            base="main",
            title="TF401028",
            body="TF401028 and TF401398 refs/heads/main",
            run=run,
        )
    assert not isinstance(refused.value, BaseMissing)


def test_a_missing_reference_that_is_not_the_base_is_a_plain_failure() -> None:
    from agent_build_kit.forges.base import BaseMissing

    def run(args, **kwargs):
        return subprocess.CompletedProcess(
            args, 1, "", "ERROR: TF401028: The reference 'refs/heads/spec/x/1' does not exist."
        )

    with pytest.raises(AzError) as refused:
        FORGE.create_pr(REPO, head="spec/x/1", base="spec/x/0", title="t", body="b", run=run)
    assert not isinstance(refused.value, BaseMissing)
