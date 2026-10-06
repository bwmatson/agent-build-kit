"""The REST documents parse into typed models, and a body that is not one is an
error that names the endpoint it came from.

The documents are the recorded shapes in `azure_answers`, nulls and fields the
code does not read included: `labels: null`, `context: null` on a queued
evaluation, `commentType: null` on a real comment.
"""

from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.azure_models import (
    BuildDoc,
    EvaluationDoc,
    PullRequestDoc,
    StatusDoc,
    ThreadDoc,
)
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.transport import TransportError
from tests.forges import azure_answers
from tests.forges.azure_rest_host import PROJECT_ID, RestHost, answer, listed

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def test_a_pull_request_document_parses() -> None:
    doc = PullRequestDoc.model_validate(listed(azure_answers.COMPLETED))

    assert doc.pull_request_id == 157
    assert doc.status == "completed"
    assert doc.merge_status == "succeeded"
    assert doc.is_draft is False
    assert doc.source_ref_name == "refs/heads/spec/add-marker/1"
    assert doc.target_ref_name == "refs/heads/main"
    assert doc.reviewers[0].vote == 10
    assert doc.repository.project.id == PROJECT_ID


def test_null_fields_parse_as_absent() -> None:
    """`labels` is null, not `[]`, on a pull request with none."""
    document = listed(azure_answers.OPEN)
    assert document["labels"] is None

    doc = PullRequestDoc.model_validate(document)

    assert not doc.labels
    assert not doc.reviewers


def test_an_unknown_field_is_ignored_at_every_level() -> None:
    document = listed(azure_answers.OPEN)
    document["aFieldAddedNextYear"] = {"nested": [1, 2]}
    document["reviewers"] = [{**azure_answers.reviewer(-5), "voteDelegatedTo": "someone"}]

    doc = PullRequestDoc.model_validate(document)

    assert doc.pull_request_id == 162
    assert doc.reviewers[0].vote == -5


def test_a_thread_parses_with_its_comments_and_context() -> None:
    doc = ThreadDoc.model_validate(azure_answers.REVIEW_THREAD)

    assert doc.id == 478
    assert doc.status == "closed"
    assert [c.id for c in doc.comments] == [1, 2, 3]
    assert (doc.comments[0].content or "").startswith("The declared schema")
    assert doc.comments[1].comment_type is None
    assert doc.thread_context is not None
    assert doc.thread_context.file_path == "/poc/validate/effective_schema.py"
    assert doc.thread_context.right_file_start is not None
    assert doc.thread_context.right_file_start.line == 14


def test_a_thread_with_no_context_parses() -> None:
    """The server's own threads carry `threadContext: null`."""
    doc = ThreadDoc.model_validate(azure_answers.SYSTEM_PUSH)

    assert doc.thread_context is None
    assert doc.comments[0].comment_type == "system"


def test_a_policy_evaluation_parses() -> None:
    doc = EvaluationDoc.model_validate(azure_answers.evaluation("rejected", "CI build"))

    assert doc.status == "rejected"
    assert doc.configuration.type.id == azure_answers.BUILD_POLICY_TYPE["id"]
    assert doc.configuration.type.display_name == "Build"
    assert doc.configuration.settings["displayName"] == "CI build"
    assert doc.context is not None
    assert doc.context.build_id == 41


def test_a_queued_evaluation_has_no_context() -> None:
    doc = EvaluationDoc.model_validate(azure_answers.evaluation("queued"))

    assert doc.context is None


def test_a_status_parses() -> None:
    doc = StatusDoc.model_validate(azure_answers.FAILED_STATUS)

    assert doc.id == 1
    assert doc.state == "failed"
    assert doc.description == "CI build failed"
    assert (doc.context.genre, doc.context.name) == ("continuous-integration", "build")
    assert (doc.target_url or "").endswith("buildId=1")


def test_a_build_parses() -> None:
    doc = BuildDoc.model_validate(
        {"id": 41, "buildNumber": "2026.41", "status": "completed", "result": "canceled"}
    )

    assert doc.id == 41
    assert doc.build_number == "2026.41"
    assert doc.result == "canceled"


def test_a_listing_with_an_unknown_field_still_lists() -> None:
    document = listed(deepcopy(azure_answers.OPEN))
    document["_links"] = {"self": {"href": "https://dev.azure.com/acme"}}
    host = RestHost(document)

    [pull] = AzureDevOpsForge(http=host).list_prs(REPO)

    assert pull.number == 162


@pytest.mark.parametrize(
    "body",
    [
        {"value": "not a list"},
        {"value": [{"status": "active"}]},
        {"value": [{"pullRequestId": "not a number", "status": "active"}]},
        {"count": 1},
    ],
    ids=["value not a list", "no id", "id not a number", "no value"],
)
def test_a_malformed_listing_raises_naming_the_endpoint(body: object) -> None:
    host = RestHost()
    host.refuse[("GET", "pullrequests")] = answer(body)

    with pytest.raises(TransportError) as caught:
        AzureDevOpsForge(http=host).list_prs(REPO)

    assert "pullrequests" in str(caught.value).lower()


def test_a_malformed_thread_list_raises_naming_its_endpoint_and_the_body() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("GET", "pullrequests/162/threads")] = answer({"value": [{"id": "x"}]})

    with pytest.raises(TransportError) as caught:
        AzureDevOpsForge(http=host).list_prs(REPO)

    message = str(caught.value)
    assert "threads" in message
    assert '{"value"' in message, "the first characters of what came back"


def test_a_malformed_evaluation_raises_naming_its_endpoint() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("GET", "policy/evaluations")] = answer({"value": [{"status": ["no"]}]})

    with pytest.raises(TransportError) as caught:
        AzureDevOpsForge(http=host).list_prs(REPO)

    assert "evaluations" in str(caught.value)


def test_a_body_that_is_not_json_raises() -> None:
    host = RestHost()
    host.refuse[("GET", "pullrequests")] = httpx.Response(
        200, content="{not json", headers={"content-type": "application/json"}
    )

    with pytest.raises(TransportError):
        AzureDevOpsForge(http=host).list_prs(REPO)
