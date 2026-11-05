"""On Azure DevOps a late check can settle from the merge commit's builds (spec:
merged-waits-for-ci, forge-pr-state): a pull request's failed check from a build policy and the
merge commit's build of the pipeline that policy runs share a name, so the merge commit's passing
build settles the unit."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId, failing_names
from agent_build_kit.pipeline import events
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
MERGE = "c" * 40


def build(number: int, result: str, definition: int, name: str) -> dict:
    return {
        "id": number,
        "status": "completed",
        "result": result,
        "sourceVersion": MERGE,
        "definition": {"id": definition, "name": name},
    }


def test_a_failed_build_policy_check_settles_from_the_merge_commit_s_passing_build() -> None:
    policy = azure_answers.evaluation("rejected", name="CI build")
    [pull] = AzureDevOpsForge(
        http=RestHost(azure_answers.OPEN, policies={162: [policy]}, builds={41: "failed"})
    ).list_prs(REPO)
    host = RestHost(
        commit_builds=[build(7, "succeeded", 3, "app-ci"), build(8, "succeeded", 9, "docs")],
        branch_policies=[policy["configuration"]],
    )

    found = AzureDevOpsForge(http=host).commit_checks(REPO, MERGE, branch="main")

    assert events.base_verdict(found, failing_names(pull.checks)) == events.BaseVerdict.PASSED


def test_a_failed_build_policy_check_whose_pipeline_failed_on_the_merge_commit_runs_locally() -> (
    None
):
    policy = azure_answers.evaluation("rejected", name="CI build")
    [pull] = AzureDevOpsForge(
        http=RestHost(azure_answers.OPEN, policies={162: [policy]}, builds={41: "failed"})
    ).list_prs(REPO)
    host = RestHost(
        commit_builds=[build(7, "failed", 3, "app-ci")],
        branch_policies=[policy["configuration"]],
    )

    found = AzureDevOpsForge(http=host).commit_checks(REPO, MERGE, branch="main")

    assert events.base_verdict(found, failing_names(pull.checks)) == events.BaseVerdict.RUN_LOCALLY
