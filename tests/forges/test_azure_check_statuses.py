"""Azure DevOps statuses and build-policy evaluations become one list of checks.

Pull request statuses can be posted many times for one context, the latest
winning; a policy evaluation says `rejected` for a failed and for a cancelled
build alike, and only the build tells them apart.
"""

from __future__ import annotations

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import CheckStatus, PullRequest, RepoId
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def one(**host: object) -> PullRequest:
    [found] = AzureDevOpsForge(http=RestHost(azure_answers.OPEN, **host)).list_prs(REPO)  # type: ignore[arg-type]
    return found


def evaluated(status: str, name: str, build: int | None) -> dict:
    document = azure_answers.evaluation(status, name)
    document["context"] = {"buildId": build, "isExpired": False} if build else None
    return document


def posted(id: int, state: str, name: str, genre: str | None = "ci") -> dict:
    return {
        "id": id,
        "state": state,
        "description": f"{name} {state}",
        "context": {"genre": genre, "name": name},
        "targetUrl": f"https://dev.azure.com/acme/_build/results?buildId={id}",
        "creationDate": "2026-09-24T18:02:11.483Z",
    }


def statuses(pull: PullRequest) -> dict[str, CheckStatus]:
    return {check.name: check.status for check in pull.checks}


# --- pull request statuses --------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "status"),
    [
        ("succeeded", CheckStatus.PASSED),
        ("failed", CheckStatus.FAILED),
        ("error", CheckStatus.FAILED),
        ("pending", CheckStatus.PENDING),
        ("notSet", CheckStatus.PENDING),
    ],
)
def test_a_posted_state_maps_to_its_status(state: str, status: CheckStatus) -> None:
    pull = one(statuses={162: [posted(1, state, "lint")]})

    assert statuses(pull) == {"ci/lint": status}


def test_a_status_that_does_not_apply_is_omitted() -> None:
    pull = one(statuses={162: [posted(1, "notApplicable", "lint")]})

    assert pull.checks == ()


def test_several_postings_for_one_context_are_one_check_and_the_latest_wins() -> None:
    older = posted(1, "failed", "tier2", genre="local")
    newer = posted(3, "pending", "tier2", genre="local")
    middle = posted(2, "succeeded", "tier2", genre="local")

    pull = one(statuses={162: [middle, newer, older]})

    assert [(c.name, c.status) for c in pull.checks] == [("local/tier2", CheckStatus.PENDING)]


def test_a_status_carries_its_target_as_the_link() -> None:
    [check] = one(statuses={162: [posted(4, "failed", "lint")]}).checks

    assert check.url == "https://dev.azure.com/acme/_build/results?buildId=4"


def test_a_status_with_no_genre_is_named_by_its_name() -> None:
    pull = one(statuses={162: [posted(1, "failed", "smoke", genre=None)]})

    assert statuses(pull) == {"smoke": CheckStatus.FAILED}


# --- build-policy evaluations -----------------------------------------------------


def test_every_evaluation_status_maps_to_its_status() -> None:
    pull = one(
        policies={
            162: [
                evaluated("approved", "lint", 40),
                evaluated("rejected", "unit", 41),
                evaluated("broken", "integration", 42),
                evaluated("rejected", "slow", 43),
                evaluated("queued", "deploy", None),
                evaluated("running", "smoke", 44),
                evaluated("notApplicable", "docs", None),
            ]
        },
        builds={41: "failed", 42: "failed", 43: "canceled"},
    )

    assert statuses(pull) == {
        "lint": CheckStatus.PASSED,
        "unit": CheckStatus.FAILED,
        "integration": CheckStatus.FAILED,
        "slow": CheckStatus.CANCELLED,
        "deploy": CheckStatus.PENDING,
        "smoke": CheckStatus.PENDING,
    }


def test_a_rejected_evaluation_whose_build_was_cancelled_is_cancelled_not_failed() -> None:
    pull = one(policies={162: [evaluated("rejected", "CI build", 41)]}, builds={41: "canceled"})

    assert statuses(pull) == {"CI build": CheckStatus.CANCELLED}


def test_a_rejected_evaluation_with_no_build_to_ask_about_is_failed() -> None:
    pull = one(policies={162: [evaluated("rejected", "CI build", None)]})

    assert statuses(pull) == {"CI build": CheckStatus.FAILED}


def test_a_policy_that_is_not_a_build_is_not_a_check() -> None:
    reviewers = {"id": "fa4e907d-c16b-4a4c-9dfa-4906e5d171dd", "displayName": "Reviewers"}
    evaluation = azure_answers.evaluation("rejected", "Reviewers", reviewers)

    assert one(policies={162: [evaluation]}).checks == ()


# --- both sources ------------------------------------------------------------------


def test_statuses_and_evaluations_are_merged_into_one_list() -> None:
    pull = one(
        statuses={162: [posted(1, "succeeded", "lint")]},
        policies={162: [evaluated("running", "CI build", 41)]},
    )

    assert statuses(pull) == {"ci/lint": CheckStatus.PASSED, "CI build": CheckStatus.PENDING}
