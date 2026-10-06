"""The label writes of the GitHub forge, through the typed client.

The host keeps the repository's labels and each pull request's, matches names
without regard to case, and creates an unknown label in its default colour when
one is put on a pull request: so what is checked is the state the writes leave,
and that the vocabulary's own colour and description get there first.
"""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import Label, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import NotFound
from tests.forges.github_host import DEFAULT_COLOUR, GitHubHost, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
RUNNING = Label(name="running", color="d97706", description="An agent is building this unit")
IN_REVIEW = Label(name="in-review", color="2563eb", description="In review")
STATE_FAMILY = ("planned", "running", "in-review", "held")


def host() -> GitHubHost:
    """A repository whose pull request 7 carries `in-review` and `bug`, and
    which has no `running` label yet."""
    return GitHubHost(
        repo_labels=[
            ("in-review", "2563eb", "In review"),
            ("bug", "d73a4a", "Something isn't working"),
        ],
        pr_labels={7: ["in-review", "bug"]},
    )


def drifted(colour: str = "2563eb", description: str = "In review") -> GitHubHost:
    """A repository whose `in-review` label is not what the vocabulary says."""
    return GitHubHost(repo_labels=[("in-review", colour, description)], pr_labels={7: []})


def forge(h: GitHubHost) -> GitHubForge:
    return GitHubForge(http=h)


def on_pull(h: GitHubHost) -> set[str]:
    return set(h.pr_labels[7])


def test_a_label_the_repo_lacks_is_created_with_its_colour_and_description() -> None:
    h = host()

    forge(h).add_label(REPO, 7, RUNNING)

    [create] = h.calls("POST", f"{BASE}/labels")
    assert create.body == {
        "name": "running",
        "color": "d97706",
        "description": "An agent is building this unit",
    }
    assert h.repo_labels["running"]["color"] == "d97706", "not the host's default colour"
    assert on_pull(h) == {"in-review", "bug", "running"}


def test_a_label_the_repo_has_is_not_created_again() -> None:
    h = host()

    forge(h).add_label(REPO, 7, IN_REVIEW)

    assert not h.calls("POST", f"{BASE}/labels")
    assert not h.calls("PATCH")


def test_a_label_the_repo_has_under_another_case_is_not_created_again() -> None:
    h = host()

    forge(h).add_label(REPO, 7, Label(name="In-Review", color="2563eb", description="In review"))

    assert not h.calls("POST", f"{BASE}/labels")
    assert set(h.repo_labels) == {"in-review", "bug"}


def test_a_label_the_repo_has_in_another_colour_is_recoloured_not_created() -> None:
    h = drifted(colour="111111")

    forge(h).add_label(REPO, 7, IN_REVIEW)

    [edit] = h.calls("PATCH", f"{BASE}/labels/in-review")
    assert edit.body["color"] == "2563eb"
    assert not h.calls("POST", f"{BASE}/labels")
    assert h.repo_labels["in-review"]["color"] == "2563eb"


def test_a_label_the_repo_has_with_another_description_is_re_described() -> None:
    h = drifted(description="Something older")

    forge(h).add_label(REPO, 7, IN_REVIEW)

    assert h.repo_labels["in-review"]["description"] == "In review"
    assert not h.calls("POST", f"{BASE}/labels")


def test_a_label_the_repo_has_as_it_is_sends_no_edit() -> None:
    h = host()

    forge(h).add_label(REPO, 7, Label(name="in-review", color="2563EB", description="In review"))

    assert not h.calls("PATCH")
    assert not h.calls("POST", f"{BASE}/labels")


def test_a_label_under_another_case_is_edited_by_the_name_the_repo_has() -> None:
    h = drifted(colour="111111")

    forge(h).add_label(REPO, 7, Label(name="In-Review", color="2563eb", description="In review"))

    assert h.calls("PATCH", f"{BASE}/labels/in-review")
    assert h.repo_labels["in-review"]["color"] == "2563eb"
    assert set(h.repo_labels) == {"in-review"}


def test_adding_a_label_puts_it_on_the_pull_request_in_the_vocabulary_s_colour() -> None:
    h = host()

    forge(h).add_label(REPO, 7, RUNNING)

    assert "running" in on_pull(h)
    assert DEFAULT_COLOUR not in {label["color"] for label in h.repo_labels.values()}


def test_setting_an_exclusive_label_removes_the_rest_of_its_family_only() -> None:
    h = host()

    forge(h).set_exclusive_label(REPO, 7, RUNNING, family=STATE_FAMILY)

    assert on_pull(h) == {"running", "bug"}, "`bug` is not the pipeline's"
    assert h.repo_labels["running"]["color"] == "d97706"


def test_an_exclusive_label_already_on_the_pull_request_stays() -> None:
    h = host()

    forge(h).set_exclusive_label(REPO, 7, IN_REVIEW, family=STATE_FAMILY)

    assert on_pull(h) == {"in-review", "bug"}


def test_removing_a_label_takes_it_off_the_pull_request() -> None:
    h = GitHubHost(
        repo_labels=[("agent-rework", "b60205", "Rework")], pr_labels={7: ["agent-rework"]}
    )

    forge(h).remove_label(REPO, 7, "agent-rework")

    assert on_pull(h) == set()
    assert h.calls("DELETE", f"{BASE}/issues/7/labels/agent-rework")


def test_removing_a_label_that_is_not_on_the_pull_request_returns_normally() -> None:
    h = GitHubHost(repo_labels=[("agent-rework", "b60205", "Rework")], pr_labels={7: []})

    forge(h).remove_label(REPO, 7, "agent-rework")

    assert h.calls("DELETE", f"{BASE}/issues/7/labels/agent-rework")


def test_a_not_found_that_is_not_about_the_label_is_raised() -> None:
    """A credential that cannot see the repository or the pull request is
    refused with a 404 too; reading it as 'label already off' would hide it."""
    h = GitHubHost(
        pr_labels={7: []},
        routes={("DELETE", f"{BASE}/issues/7/labels/agent-rework"): refusal(404, "Not Found")},
    )

    with pytest.raises(NotFound):
        forge(h).remove_label(REPO, 7, "agent-rework")
