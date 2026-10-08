"""Every operation the forge performs is a REST call, and none starts a process.

The host is the REST stand-in, so what is checked is the request the forge
sends (method, resource, version, body) and what it makes of the answer. The
`rest_env` fixture fails the test if a subprocess is started.
"""

from __future__ import annotations

import logging

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import BaseMissing, Label, PullRequest, RepoId
from agent_build_kit.forges.transport import AuthError, TransportError
from tests.forges import azure_answers
from tests.forges.azure_rest_host import NO_OBJECT, RestHost, answer, refusal

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
HEAD = "spec/add-marker/1"


def forge(host: RestHost) -> AzureDevOpsForge:
    return AzureDevOpsForge(http=host)


# --- where every call goes --------------------------------------------------------


def test_every_call_names_its_organisation_project_and_repository() -> None:
    host = RestHost(azure_answers.OPEN)

    forge(host).list_prs(REPO)

    for call in host.seen:
        assert call.request.url.host == "dev.azure.com"
        assert call.request.url.path.startswith("/acme/Some Project/_apis/"), call.request.url.path
    repository = host.calls("GET", "pullrequests")[0].request.url.path
    assert "/_apis/git/repositories/Some Repo/pullrequests" in repository


def test_the_api_version_is_pinned_and_the_preview_one_is_the_evaluations() -> None:
    host = RestHost(
        azure_answers.OPEN,
        policies={162: [azure_answers.evaluation("broken")]},
        builds={41: "failed"},
    )

    forge(host).list_prs(REPO)

    versions = {c.route: c.params["api-version"] for c in host.seen}
    assert versions.pop("policy/evaluations") == "7.1-preview.1"
    assert set(versions.values()) == {"7.1"}


# --- creating and finding ---------------------------------------------------------


def test_creating_a_pull_request_posts_it_and_returns_the_id() -> None:
    host = RestHost()

    number = forge(host).create_pr(REPO, head=HEAD, base="main", title="T", body="B")

    [call] = host.writes()
    assert (call.method, call.route) == ("POST", "pullrequests")
    assert call.body == {
        "sourceRefName": f"refs/heads/{HEAD}",
        "targetRefName": "refs/heads/main",
        "title": "T",
        "description": "B",
    }
    assert number == 300


@pytest.mark.parametrize(
    "message",
    [
        "TF401028: The reference 'refs/heads/spec/x/0' does not exist. Check the name.",
        "TF401398: The pull request cannot be activated because the source and/or the target "
        "branch no longer exists.",
    ],
)
def test_a_refusal_for_a_missing_base_is_its_own_error(message: str) -> None:
    host = RestHost()
    host.refuse[("POST", "pullrequests")] = refusal(400, message)

    with pytest.raises(BaseMissing):
        forge(host).create_pr(REPO, head="spec/x/1", base="spec/x/0", title="t", body="b")


def test_a_refusal_that_is_not_about_the_base_is_a_plain_failure_whatever_the_body_quotes() -> None:
    host = RestHost()
    host.refuse[("POST", "pullrequests")] = refusal(
        403, "TF401027: You need the GenericContribute permission."
    )

    with pytest.raises(TransportError) as caught:
        forge(host).create_pr(
            REPO, head="spec/x/1", base="main", title="TF401028", body="TF401398 refs/heads/main"
        )

    assert not isinstance(caught.value, BaseMissing)
    assert "TF401027" in str(caught.value), "what the host said"


def test_a_missing_reference_that_is_not_the_base_is_a_plain_failure() -> None:
    host = RestHost()
    host.refuse[("POST", "pullrequests")] = refusal(
        400, "TF401028: The reference 'refs/heads/spec/x/1' does not exist."
    )

    with pytest.raises(TransportError) as caught:
        forge(host).create_pr(REPO, head="spec/x/1", base="spec/x/0", title="t", body="b")

    assert not isinstance(caught.value, BaseMissing)


def test_finding_a_pull_request_by_its_branch() -> None:
    other = azure_answers.pull(pullRequestId=170, sourceRefName="refs/heads/spec/other/1")
    host = RestHost(other, azure_answers.OPEN)

    assert forge(host).find_pr(REPO, head=HEAD) == 162
    [call] = host.calls("GET", "pullrequests")
    assert call.params["searchCriteria.sourceRefName"] == f"refs/heads/{HEAD}"
    assert call.params["searchCriteria.status"] == "all"
    assert call.params["$top"] == "1"


def test_a_branch_with_no_pull_request_yet() -> None:
    assert forge(RestHost(azure_answers.OPEN)).find_pr(REPO, head="spec/none/1") is None


# --- updating ---------------------------------------------------------------------


def test_retargeting_patches_the_base_when_it_differs() -> None:
    host = RestHost(azure_answers.OPEN)

    forge(host).update_pr(REPO, 162, base="spec/other/0")

    [call] = host.writes()
    assert (call.method, call.route) == ("PATCH", "pullrequests/162")
    assert call.body == {"targetRefName": "refs/heads/spec/other/0"}
    assert call.params["api-version"] == "7.1"


def test_a_base_already_equal_to_the_target_makes_no_write() -> None:
    """Azure answers a retarget to the branch a PR already has with a 400, which
    failed every rework of a pull request opened on the right branch."""
    host = RestHost(azure_answers.OPEN)

    forge(host).update_pr(REPO, 162, base="main")

    assert host.writes() == []
    assert [c.route for c in host.seen] == ["pullrequests/162"]


def test_the_body_is_patched_as_the_description() -> None:
    host = RestHost(azure_answers.OPEN)

    forge(host).update_pr(REPO, 162, body="new text")

    [call] = host.writes()
    assert (call.method, call.route, call.body) == (
        "PATCH",
        "pullrequests/162",
        {"description": "new text"},
    )


def test_a_base_and_a_body_are_two_patches_and_one_read() -> None:
    host = RestHost(azure_answers.OPEN)

    forge(host).update_pr(REPO, 162, base="spec/other/0", body="new text")

    assert [c.body for c in host.writes()] == [
        {"targetRefName": "refs/heads/spec/other/0"},
        {"description": "new text"},
    ]


def test_a_refusal_says_what_azure_said() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("PATCH", "pullrequests/162")] = refusal(400, "TF401180: not a valid target")

    with pytest.raises(TransportError, match="TF401180"):
        forge(host).update_pr(REPO, 162, base="spec/other/0")


# --- threads ----------------------------------------------------------------------


def test_a_reply_lands_in_the_thread_it_answers() -> None:
    host = RestHost(azure_answers.OPEN)

    made = forge(host).post_reply(REPO, 162, note_id="478.1", body="Fixed.")

    [call] = host.writes()
    assert (call.method, call.route) == ("POST", "pullrequests/162/threads/478/comments")
    assert call.body == {"content": "Fixed.", "parentCommentId": 1, "commentType": 1}
    assert made == ["478.4"]


def test_a_summary_opens_a_thread_of_its_own() -> None:
    host = RestHost(azure_answers.OPEN)

    made = forge(host).post_comment(REPO, 162, body="Summary")

    [call] = host.writes()
    assert (call.method, call.route) == ("POST", "pullrequests/162/threads")
    assert call.body == {"comments": [{"content": "Summary", "commentType": 1}], "status": "active"}
    assert made == ["900.1"]


# --- labels -----------------------------------------------------------------------


def test_adding_a_label_posts_only_its_name() -> None:
    host = RestHost(azure_answers.OPEN)

    forge(host).add_label(REPO, 162, Label(name="in-review", color="ff0000", description="d"))

    [call] = host.writes()
    assert (call.method, call.route, call.body) == (
        "POST",
        "pullrequests/162/labels",
        {"name": "in-review"},
    )


def test_a_label_in_another_case_is_kept_not_duplicated() -> None:
    host = RestHost(azure_answers.OPEN, labels={162: ["in-review"]})

    forge(host).add_label(REPO, 162, Label(name="In-Review", color="ff0000"))

    assert host.label_names(162) == ["in-review"]


def test_removing_a_label_is_one_delete_by_name() -> None:
    host = RestHost(azure_answers.OPEN, labels={162: ["in-review"]})

    forge(host).remove_label(REPO, 162, "in-review")

    assert [(c.method, c.route) for c in host.seen] == [
        ("DELETE", "pullrequests/162/labels/in-review")
    ]
    assert host.label_names(162) == []


def test_removing_a_label_that_is_not_there_returns_normally() -> None:
    forge(RestHost(azure_answers.OPEN)).remove_label(REPO, 162, "in-review")


def test_any_other_refusal_to_remove_a_label_raises() -> None:
    host = RestHost(azure_answers.OPEN, labels={162: ["in-review"]})
    host.refuse[("DELETE", "pullrequests/162/labels/in-review")] = refusal(403, "TF401027")

    with pytest.raises(AuthError):
        forge(host).remove_label(REPO, 162, "in-review")


def test_an_exclusive_label_replaces_the_rest_of_its_family() -> None:
    host = RestHost(azure_answers.OPEN, labels={162: ["Needs-Rework", "unrelated"]})

    forge(host).set_exclusive_label(
        REPO,
        162,
        Label(name="in-review", color="ff0000"),
        family=["in-review", "needs-rework"],
    )

    assert sorted(host.label_names(162)) == ["in-review", "unrelated"]
    assert [(c.method, c.route) for c in host.writes()] == [
        ("POST", "pullrequests/162/labels"),
        ("DELETE", "pullrequests/162/labels/needs-rework"),
    ]


# --- statuses ---------------------------------------------------------------------


def post(host: RestHost, *, ok: bool = True, head: str = HEAD, description: str = "4 passed"):
    forge(host).post_status(
        REPO, sha="abc123", ok=ok, context="local/tier2", description=description, head=head
    )


def test_a_result_is_posted_on_the_commit_and_on_the_open_pull_request() -> None:
    host = RestHost(azure_answers.OPEN)

    post(host)

    commit, on_pr = host.writes()
    expected = {
        "state": "succeeded",
        "description": "4 passed",
        "context": {"genre": "local", "name": "tier2"},
    }
    assert (commit.method, commit.route, commit.body) == (
        "POST",
        "commits/abc123/statuses",
        expected,
    )
    assert (on_pr.method, on_pr.route, on_pr.body) == (
        "POST",
        "pullrequests/162/statuses",
        expected,
    )


def test_a_failed_result_posts_failed() -> None:
    host = RestHost(azure_answers.OPEN)

    post(host, ok=False)

    assert [c.body["state"] for c in host.writes()] == ["failed", "failed"]


def test_a_context_with_no_slash_keeps_abk_s_own_genre() -> None:
    host = RestHost(azure_answers.OPEN)

    forge(host).post_status(REPO, sha="abc123", ok=True, context="smoke", description="d")

    [commit] = host.writes()
    assert commit.body["context"] == {"genre": "abk", "name": "smoke"}


def test_a_long_description_is_cut_by_the_forge() -> None:
    host = RestHost(azure_answers.OPEN)

    post(host, description="x" * 5000)

    assert len(host.writes()[0].body["description"]) <= 950


def test_the_pull_request_looked_up_is_the_active_one_for_the_head() -> None:
    other = azure_answers.pull(pullRequestId=170, sourceRefName="refs/heads/spec/other/1")
    host = RestHost(other, azure_answers.OPEN)

    post(host)

    [lookup] = host.calls("GET", "pullrequests")
    assert lookup.params["searchCriteria.status"] == "active"
    assert lookup.params["searchCriteria.sourceRefName"] == f"refs/heads/{HEAD}"
    assert [c.route for c in host.writes()] == [
        "commits/abc123/statuses",
        "pullrequests/162/statuses",
    ]


@pytest.mark.parametrize("head", ["spec/nothing-here/1", ""])
def test_no_pull_request_for_the_head_posts_only_the_commit_status(head: str) -> None:
    host = RestHost(azure_answers.OPEN)

    post(host, head=head)

    assert [c.route for c in host.writes()] == ["commits/abc123/statuses"]


def test_a_finished_pull_request_is_not_written_to() -> None:
    host = RestHost(azure_answers.COMPLETED, azure_answers.ABANDONED)

    post(host)

    assert [c.route for c in host.writes()] == ["commits/abc123/statuses"]


def test_a_refused_pull_request_status_is_a_warning_not_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("POST", "pullrequests/162/statuses")] = refusal(
        403, "TF401027: GenericContribute required"
    )

    with caplog.at_level(logging.WARNING):
        post(host)

    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert [c.route for c in host.writes()][0] == "commits/abc123/statuses"


def test_a_refused_commit_status_is_advisory_and_does_not_raise() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("POST", "commits/abc123/statuses")] = refusal(400, "TF400898: no")

    post(host)

    assert [c.route for c in host.writes()] == ["commits/abc123/statuses"]


# --- files, closing, draft, branches ----------------------------------------------


def test_the_changed_files_come_from_the_newest_iteration() -> None:
    host = RestHost(azure_answers.OPEN)

    files = forge(host).pr_files(REPO, 162)

    assert files == ["poc/validate/params.py", "poc/validate/verdict.py"]
    assert [c.route for c in host.seen] == [
        "pullrequests/162/iterations",
        "pullrequests/162/iterations/5/changes",
    ]


def test_closing_abandons_with_one_patch() -> None:
    host = RestHost(azure_answers.OPEN)

    forge(host).close_pr(REPO, 162)

    [call] = host.seen
    assert (call.method, call.route, call.body) == (
        "PATCH",
        "pullrequests/162",
        {"status": "abandoned"},
    )


def test_a_close_that_fails_raises() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("PATCH", "pullrequests/162")] = refusal(400, "TF401181: cannot abandon")

    with pytest.raises(TransportError, match="TF401181"):
        forge(host).close_pr(REPO, 162)


@pytest.mark.parametrize("draft", [True, False])
def test_draft_is_written_only_on_a_change(draft: bool) -> None:
    host = RestHost(azure_answers.pull(isDraft=not draft))

    forge(host).set_draft(REPO, 162, draft)

    [read, write] = host.seen
    assert (read.method, read.route) == ("GET", "pullrequests/162")
    assert (write.method, write.route, write.body) == (
        "PATCH",
        "pullrequests/162",
        {"isDraft": draft},
    )


@pytest.mark.parametrize("draft", [True, False])
def test_a_draft_already_as_asked_makes_no_write(draft: bool) -> None:
    host = RestHost(azure_answers.pull(isDraft=draft))

    forge(host).set_draft(REPO, 162, draft)

    assert host.writes() == []


def test_deleting_a_branch_names_the_commit_it_points_at() -> None:
    oid = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    host = RestHost(refs={f"heads/{HEAD}": oid, f"heads/{HEAD}-other": "f" * 40})

    forge(host).delete_remote_branch(REPO, HEAD)

    [lookup] = host.calls("GET", "refs")
    assert lookup.params["filter"] == f"heads/{HEAD}"
    [write] = host.writes()
    assert (write.method, write.route) == ("POST", "refs")
    assert write.body == [
        {"name": f"refs/heads/{HEAD}", "oldObjectId": oid, "newObjectId": NO_OBJECT}
    ]


def test_a_refused_ref_delete_raises_with_the_reason() -> None:
    host = RestHost(refs={f"heads/{HEAD}": "a" * 40}, ref_status="staleOldObjectId")

    with pytest.raises(TransportError, match=f"{HEAD}.*staleOldObjectId"):
        forge(host).delete_remote_branch(REPO, HEAD)


def test_a_branch_already_gone_is_not_an_error() -> None:
    host = RestHost(refs={f"heads/{HEAD}-other": "f" * 40})

    forge(host).delete_remote_branch(REPO, HEAD)

    assert host.writes() == []


# --- re-running, access, guard ----------------------------------------------------


def test_only_the_cancelled_builds_evaluation_is_queued_again() -> None:
    cancelled = {**azure_answers.evaluation("broken", "CI build"), "evaluationId": "eval-41"}
    failed = {
        **azure_answers.evaluation("broken", "lint"),
        "evaluationId": "eval-42",
        "context": {"buildId": 42},
    }
    host = RestHost(
        azure_answers.pull(pullRequestId=16),
        policies={16: [cancelled, failed]},
        builds={41: "canceled", 42: "failed"},
    )
    pull = PullRequest(number=16, head=HEAD, base="main", state="open")

    forge(host).rerun_checks(REPO, pull)

    [call] = host.writes()
    assert (call.method, call.route) == ("PATCH", "policy/evaluations/eval-41")
    assert call.params["api-version"] == "7.1-preview.1"


def test_access_is_proved_by_reading_the_repository() -> None:
    host = RestHost()

    assert forge(host).check_access(REPO) == ""
    assert [(c.method, c.route) for c in host.seen] == [("GET", "")]


def test_a_repository_that_cannot_be_read_says_so() -> None:
    host = RestHost()
    host.refuse[("GET", "")] = refusal(401, "TF400813: not authorized")

    reason = forge(host).check_access(REPO)

    assert "Some Repo" in reason and "Some Project" in reason


def test_no_branch_policy_is_said_out_loud() -> None:
    host = RestHost(branch_policies=[])

    assert "no branch policy" in forge(host).merge_guard(REPO, branch="main")
    assert [c.route for c in host.seen] == ["policy/configurations"]


def test_a_branch_policy_means_the_server_guards_the_merge() -> None:
    host = RestHost(branch_policies=[{"id": 12, "isEnabled": True, "isBlocking": True}])

    assert forge(host).merge_guard(REPO, branch="main") == ""


def test_a_guard_that_cannot_be_read_says_so() -> None:
    host = RestHost()
    host.refuse[("GET", "policy/configurations")] = answer({"message": "no"}, 400)

    assert "cannot tell what guards main" in forge(host).merge_guard(REPO, branch="main")


# --- no process -------------------------------------------------------------------


def test_no_operation_starts_a_subprocess() -> None:
    """`rest_env` makes starting one an AssertionError; this runs the whole
    surface once under it."""
    host = RestHost(azure_answers.OPEN, labels={162: ["x"]}, refs={f"heads/{HEAD}": "a" * 40})
    f = forge(host)
    pull = f.list_prs(REPO)[0]

    f.find_pr(REPO, head=HEAD)
    f.create_pr(REPO, head="spec/y/1", base="main", title="t", body="b")
    f.update_pr(REPO, 162, base="other", body="b")
    f.post_comment(REPO, 162, body="b")
    f.post_reply(REPO, 162, note_id="1.1", body="b")
    f.add_label(REPO, 162, Label(name="y", color="000000"))
    f.set_exclusive_label(REPO, 162, Label(name="z", color="000000"), family=["x", "z"])
    f.remove_label(REPO, 162, "z")
    post(host)
    f.pr_files(REPO, 162)
    f.review_notes(REPO, 162)
    f.failed_check_logs(REPO, pull)
    f.set_draft(REPO, 162, True)
    f.close_pr(REPO, 162)
    f.delete_remote_branch(REPO, HEAD)
    f.check_access(REPO)
    f.merge_guard(REPO, branch="main")
