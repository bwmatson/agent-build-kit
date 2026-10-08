"""A forge states the longest description its host takes, and cuts to it.

The pipeline hands a forge a description it has already tried to fit; what is
still over is the forge's to cut, on a line boundary, with any open code fence
or details block closed and a note saying so. Both hosts are the REST
stand-ins, so what is checked is the request the forge sends.
"""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.github_host import GitHubHost, answer
from tests.forges.stand_in import StandInForge

AZURE_REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
GITHUB_REPO = RepoId(forge="github", account="example", name="app")
GITHUB_PULLS = "/repos/example/app/pulls"
NOTE = "_Description cut to fit the host's limit._"


def lined(count: int, width: int = 60) -> str:
    """`count` distinct lines, so a cut can be checked to fall between them."""
    return "\n".join(f"line {number:04d} " + "x" * width for number in range(count))


def fenced(count: int) -> str:
    """Output inside a code fence inside a details block, as a tier 2 report has it."""
    return (
        "## Tier 2 results\n\n- **Result:** 1 passed, 0 failed\n\n"
        "<details>\n<summary>Full output</summary>\n\n```\n"
        + lined(count)
        + "\n```\n\n</details>\n\n## How this was built\n"
    )


def azure_sent(host: RestHost) -> str:
    [call] = host.writes()
    return call.body["description"]


def github_created() -> httpx.Response:
    return answer(
        {
            "number": 7,
            "node_id": "PR_kwDOAAAAAc00000007",
            "state": "open",
            "html_url": "https://github.com/example/app/pull/7",
            "head": {"ref": "spec/add-marker/1"},
            "base": {"ref": "main"},
        },
        201,
    )


def assert_cut_on_a_line(sent: str, original: str) -> None:
    """Every line the forge sent is one it was given, or a closer, or the note."""
    given = set(original.splitlines())
    for line in sent.splitlines():
        assert line in given or line in {"```", "</details>", NOTE, ""}, line


# --- the limits -------------------------------------------------------------------


def test_the_limits_are_the_hosts() -> None:
    assert GitHubForge().description_limit == 65_536
    assert AzureDevOpsForge().description_limit == 4_000


def test_the_stand_in_states_a_positive_limit() -> None:
    assert StandInForge().description_limit > 0


# --- creating ---------------------------------------------------------------------


@pytest.mark.usefixtures("rest_env")
def test_azure_creating_cuts_to_the_limit_and_ends_with_the_note() -> None:
    host = RestHost()
    body = lined(100)
    assert len(body) > 6_000

    AzureDevOpsForge(http=host).create_pr(
        AZURE_REPO, head="spec/add-marker/1", base="main", title="T", body=body
    )

    sent = azure_sent(host)
    assert len(sent) <= 4_000
    assert sent.rstrip().endswith(NOTE)
    assert_cut_on_a_line(sent, body)


@pytest.mark.usefixtures("github_env")
def test_github_creating_cuts_to_its_own_limit() -> None:
    host = GitHubHost(routes={("POST", GITHUB_PULLS): github_created()})
    body = lined(1_200)
    assert len(body) > 65_536

    GitHubForge(http=host).create_pr(
        GITHUB_REPO, head="spec/add-marker/1", base="main", title="t", body=body
    )

    [call] = host.calls("POST", GITHUB_PULLS)
    assert len(call.body["body"]) <= 65_536
    assert call.body["body"].rstrip().endswith(NOTE)
    assert_cut_on_a_line(call.body["body"], body)


# --- updating ---------------------------------------------------------------------


@pytest.mark.usefixtures("rest_env")
def test_azure_updating_cuts_too() -> None:
    host = RestHost(azure_answers.OPEN)

    AzureDevOpsForge(http=host).update_pr(AZURE_REPO, 162, body=lined(100))

    sent = azure_sent(host)
    assert len(sent) <= 4_000
    assert sent.rstrip().endswith(NOTE)


@pytest.mark.usefixtures("github_env")
def test_github_updating_cuts_too() -> None:
    route = ("PATCH", f"{GITHUB_PULLS}/7")
    host = GitHubHost(routes={route: answer({"number": 7})})

    GitHubForge(http=host).update_pr(GITHUB_REPO, 7, body=lined(1_200))

    [call] = host.calls(*route)
    assert len(call.body["body"]) <= 65_536
    assert call.body["body"].rstrip().endswith(NOTE)


# --- closing what the cut left open -----------------------------------------------


@pytest.mark.usefixtures("rest_env")
def test_a_cut_inside_a_fence_in_a_details_block_closes_both_before_the_note() -> None:
    host = RestHost()

    AzureDevOpsForge(http=host).create_pr(
        AZURE_REPO, head="spec/add-marker/1", base="main", title="T", body=fenced(100)
    )

    sent = azure_sent(host)
    assert len(sent) <= 4_000
    assert sent.count("```") % 2 == 0, "the fence is closed"
    assert sent.count("<details>") == sent.count("</details>"), "the details block is closed"
    before_note = sent.rstrip().removesuffix(NOTE).rstrip()
    assert before_note.endswith("</details>")
    assert sent.rstrip().endswith(NOTE)


@pytest.mark.usefixtures("rest_env")
def test_a_cut_inside_details_alone_closes_the_block() -> None:
    host = RestHost()
    body = "<details>\n<summary>More</summary>\n\n" + lined(100) + "\n</details>\n"

    AzureDevOpsForge(http=host).create_pr(
        AZURE_REPO, head="spec/add-marker/1", base="main", title="T", body=body
    )

    sent = azure_sent(host)
    assert len(sent) <= 4_000
    assert sent.count("<details>") == sent.count("</details>")


# --- what fits is sent as it was --------------------------------------------------


@pytest.mark.usefixtures("rest_env")
@pytest.mark.parametrize("size", [50, 3_999, 4_000])
def test_a_body_within_the_limit_is_sent_as_it_was(size: int) -> None:
    host = RestHost()
    body = "y" * size

    AzureDevOpsForge(http=host).create_pr(
        AZURE_REPO, head="spec/add-marker/1", base="main", title="T", body=body
    )

    assert azure_sent(host) == body


@pytest.mark.usefixtures("rest_env")
def test_a_short_update_is_sent_as_it_was() -> None:
    host = RestHost(azure_answers.OPEN)

    AzureDevOpsForge(http=host).update_pr(AZURE_REPO, 162, body="new text")

    assert azure_sent(host) == "new text"
