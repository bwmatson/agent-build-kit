"""Threads, replies, the summary and the decision are kept per unit, survive a
restart and follow the branch (spec: ui-review)."""

from __future__ import annotations

from typing import Any

import httpx

from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server
from tests.factories import git
from tests.review_repo import TWO, advance, commit, rev, seed_branches
from tests.serving import seed_pipeline, seed_review_round

THREADS = "/api/units/feature/2/review/threads"
DECISION = "/api/units/feature/2/review/decision"


def comment(api: httpx.Client, **fields: Any) -> dict[str, Any]:
    body = {"path": "two.py", "side": "new", "line": 3, "body": "why this?", **fields}
    answer = api.post(THREADS, json=body)
    assert answer.is_success, answer.text
    return answer.json()


def review(api: httpx.Client) -> dict[str, Any]:
    return api.get("/api/units/feature/2/review").json()


def test_a_thread_is_stored_with_its_anchor_and_the_commit_it_was_made_at(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)

    thread = comment(api)

    assert (thread["path"], thread["side"], thread["line"]) == ("two.py", "new", 3)
    assert thread["commit"] == rev(repo, "spec/feature/2")
    assert (thread["body"], thread["replies"], thread["resolved"]) == ("why this?", [], False)
    assert thread["outdated"] is False
    assert thread["id"]
    assert review(api)["threads"] == [thread]


def test_a_thread_can_anchor_to_a_range_and_to_the_old_side(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    ranged = comment(api, start_line=2, line=4)
    old = comment(api, side="old", path="base.txt", line=1)

    assert (ranged["start_line"], ranged["line"]) == (2, 4)
    assert (old["side"], old["path"]) == ("old", "base.txt")
    assert old["id"] != ranged["id"]


def test_replies_and_resolving_are_kept_on_the_thread(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    thread = comment(api)

    first = api.post(f"{THREADS}/{thread['id']}/replies", json={"body": "because"})
    api.post(f"{THREADS}/{thread['id']}/replies", json={"body": "ok"})
    resolved = api.patch(f"{THREADS}/{thread['id']}", json={"resolved": True})

    assert first.is_success and resolved.is_success
    [stored] = review(api)["threads"]
    assert [reply["body"] for reply in stored["replies"]] == ["because", "ok"]
    assert stored["resolved"] is True
    assert api.post(f"{THREADS}/nope/replies", json={"body": "x"}).status_code == 404


def test_threads_replies_summary_and_decision_survive_a_restart(inst: Installation) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    seed_review_round(inst, "feature/2", 1)
    with start_server(inst) as server, httpx.Client(base_url=server.url) as first:
        thread = comment(first)
        first.post(f"{THREADS}/{thread['id']}/replies", json={"body": "because"})
        first.put(DECISION, json={"decision": "request_changes", "summary": "Needs a test"})
        before = review(first)

    with start_server(inst) as server, httpx.Client(base_url=server.url) as second:
        after = review(second)

    assert after == before
    assert [t["replies"][0]["body"] for t in after["threads"]] == ["because"]
    assert after["decisions"][0]["summary"] == "Needs a test"


def test_a_thread_is_outdated_once_the_branch_moves_and_keeps_its_line_where_lines_match(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    anchored = comment(api, line=3)["commit"]

    advance(repo, "spec/feature/2", "two.py", TWO + "appended\n")
    [moved] = review(api)["threads"]

    assert moved["outdated"] is True
    assert moved["line"] == 3
    assert moved["commit"] == anchored


def test_a_thread_is_relocated_when_lines_are_inserted_above_it(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    comment(api, line=3)

    advance(repo, "spec/feature/2", "two.py", "new first\nnew second\n" + TWO)
    [moved] = review(api)["threads"]

    assert moved["outdated"] is True
    assert moved["line"] == 5


def test_a_thread_is_anchored_to_the_commit_of_the_diff_it_was_made_on(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    shown = api.get("/api/units/feature/2/diff").json()["commit"]
    advance(repo, "spec/feature/2", "two.py", "new first\nnew second\n" + TWO)

    thread = comment(api, line=3, commit=shown)

    assert thread["commit"] == shown
    [stored] = review(api)["threads"]
    assert (stored["commit"], stored["outdated"], stored["line"]) == (shown, True, 5)


def test_a_thread_on_a_commit_that_is_not_there_is_refused(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    for bad in ("0" * 40, "--all"):
        answer = api.post(THREADS, json={"path": "two.py", "line": 3, "body": "x", "commit": bad})
        assert answer.status_code == 409
    assert review(api)["threads"] == []


def test_an_anchor_must_be_a_line_or_a_range_that_runs_forward(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    for anchor in (
        {"line": 0},
        {"line": -2},
        {"line": 3, "start_line": 0},
        {"line": 3, "start_line": 5},
    ):
        answer = api.post(THREADS, json={"path": "two.py", "body": "x", **anchor})
        assert answer.status_code == 422, anchor
    assert review(api)["threads"] == []


def test_a_thread_whose_commit_is_gone_is_outdated_with_no_line(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    # A commit only a dropped branch holds, then collected.
    git(repo, "checkout", "-q", "-b", "scratch", "spec/feature/2")
    lost = commit(repo, "two.py", TWO + "lost\n", "lost")
    git(repo, "checkout", "-q", "main")
    thread = comment(api, line=3, commit=lost)
    git(repo, "branch", "-q", "-D", "scratch")
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "-q", "--prune=now")

    [stored] = review(api)["threads"]

    assert (stored["id"], stored["outdated"], stored["line"]) == (thread["id"], True, None)


def test_a_thread_whose_line_was_changed_is_outdated_with_no_line(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    comment(api, line=3)

    advance(repo, "spec/feature/2", "two.py", TWO.replace("two line 3", "rewritten"))
    [moved] = review(api)["threads"]

    assert moved["outdated"] is True
    assert moved["line"] is None


def test_the_decision_and_summary_are_stored_once_per_round(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    seed_review_round(inst, "feature/2", 1)

    first = api.put(DECISION, json={"decision": "request_changes", "summary": "Needs a test"})
    again = api.put(DECISION, json={"decision": "approve", "summary": "Fine"})

    assert first.is_success
    assert again.status_code == 409
    stored = review(api)
    assert stored["round"] == 1
    assert [(d["round"], d["decision"], d["summary"]) for d in stored["decisions"]] == [
        (1, "request_changes", "Needs a test")
    ]

    seed_review_round(inst, "feature/2", 2)
    second = api.put(DECISION, json={"decision": "approve", "summary": "Fine now"})

    assert second.is_success
    assert [(d["round"], d["decision"]) for d in review(api)["decisions"]] == [
        (1, "request_changes"),
        (2, "approve"),
    ]


def test_a_decision_must_be_request_changes_or_approve(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    seed_review_round(inst, "feature/2", 1)

    answer = api.put(DECISION, json={"decision": "merge"})

    assert answer.status_code == 422
    assert review(api)["decisions"] == []


def test_a_unit_with_nothing_reviewed_has_an_empty_review(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    body = review(api)

    assert (body["threads"], body["decisions"]) == ([], [])
    assert api.get("/api/units/feature/99/review").status_code == 404
