"""Pull requests are linked to GitHub issues without closing them, the host setting picks the API
base, and the doctor probe says what the owner, token and target allow."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.tracker_file import Synced, TrackerFile, mapping_target, write_tracker
from agent_build_kit.trackers.base import PULL_REQUEST_RELATION, ProbeLine
from agent_build_kit.trackers.config import section_for
from agent_build_kit.trackers.github import GithubIssues
from agent_build_kit.trackers.pr_attach import link_lines
from tests.factories import stored_unit
from tests.trackers.github_issue_host import ENTERPRISE_PREFIX, IssueHost
from tests.trackers.github_support import section, tracker_on
from tests.trackers.tracker_section_support import GITHUB_BLOCK, configure

pytestmark = pytest.mark.usefixtures("github_env")

CHANGE = "feature"
# What a host closes an issue for when a description says it before the issue's number.
CLOSING_KEYWORDS = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b", re.IGNORECASE)
PR_URL = "https://github.com/example/app/pull/7"


def record_issues(changes_dir: Path, groups: dict[int, str]) -> None:
    """The change issue (#10) and the group issues a sync recorded, as `tracker.yaml` holds them."""
    configure(app={"kind": "github", "levels": ["change", "group"], "github": GITHUB_BLOCK})
    section = section_for("app")
    assert section is not None
    folder = changes_dir / CHANGE
    folder.mkdir(parents=True)
    write_tracker(
        folder,
        TrackerFile(
            kind=section.kind,
            target=mapping_target(section),
            change=Synced(id="10"),
            groups={f"{CHANGE}:{group}": Synced(id=number) for group, number in groups.items()},
        ),
    )


def test_a_pull_request_is_linked_by_a_comment_on_the_issue() -> None:
    host = IssueHost()
    group = host.seed("Group", type="Story")

    relation = tracker_on(host).link(group, PULL_REQUEST_RELATION, PR_URL)

    assert [PR_URL in note for note in host.comments[int(group)]] == [True]
    assert (relation.kind, relation.source_id, relation.target_id) == (
        PULL_REQUEST_RELATION,
        group,
        PR_URL,
    )


def test_the_description_has_part_of_lines_with_no_closing_keyword(tmp_path: Path) -> None:
    record_issues(tmp_path, {1: "11", 2: "12", 3: "13"})
    unit = stored_unit(f"{CHANGE}/1", change=CHANGE, groups=(1, 2), repo="app")

    lines = link_lines(unit, tmp_path)

    assert lines.splitlines() == ["Part of #11", "Part of #12"]
    assert not CLOSING_KEYWORDS.search(lines)


def test_an_enterprise_host_gets_its_own_api_base_and_the_default_the_public_one() -> None:
    enterprise, public = IssueHost(), IssueHost()
    tracker = GithubIssues(section(host="github.example.com"), http=enterprise)

    tracker.create("change", "Change", markers=("feature",))
    tracker_on(public).create("change", "Change", markers=("feature",))

    assert {request.url.host for request in enterprise.seen} == {"github.example.com"}
    assert all(request.url.path.startswith(f"{ENTERPRISE_PREFIX}/") for request in enterprise.seen)
    assert {request.url.host for request in public.seen} == {"api.github.com"}


def failures(lines: list[ProbeLine]) -> list[str]:
    return [line.text for line in lines if not line.ok]


def reports(lines: list[ProbeLine], word: str) -> bool:
    return any(line.ok and word in line.text.lower() for line in lines)


@pytest.mark.parametrize(
    ("mode", "owner_kind", "types"),
    [("organization", "organization", "issue types"), ("user", "user", "labels")],
)
def test_the_probe_reports_the_owner_kind_types_sub_issues_and_scope(
    mode: str, owner_kind: str, types: str
) -> None:
    host = IssueHost(owner_kind="Organization" if mode == "organization" else "User")

    lines = tracker_on(host, mode).probe()

    assert failures(lines) == []
    assert [
        word
        for word in (owner_kind, types, "sub-issues", "scope", "sync-account")
        if not reports(lines, word)
    ] == []


def test_a_host_without_sub_issues_is_reported_as_a_problem() -> None:
    host = IssueHost(sub_issues_enabled=False)
    host.seed("Change")

    [text] = failures(tracker_on(host).probe())

    assert "sub-issues" in text


def test_a_token_refused_for_single_sign_on_reads_not_authorized_for_the_owner() -> None:
    lines = tracker_on(IssueHost(unauthorized=True)).probe()

    assert any("token not authorized for example" in text for text in failures(lines))
    assert not any("target not found" in text for text in failures(lines))


def test_a_missing_repository_reads_target_not_found() -> None:
    lines = tracker_on(IssueHost(repo_exists=False)).probe()

    assert any("target not found" in text for text in failures(lines))
    assert not any("not authorized" in text for text in failures(lines))
