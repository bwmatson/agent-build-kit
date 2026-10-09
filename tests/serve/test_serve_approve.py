"""Approve from a unit's page records the person's approval of the round at the head
the pull request has, and does nothing else (spec: web-ui, Approve records the
person's approval and does nothing else)."""

from __future__ import annotations

import httpx

from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server
from tests.review_approval import (
    give_a_remote,
    refs,
    stored_decisions,
    watch_the_host,
    without_a_branch,
    write_an_old_decision,
)
from tests.review_repo import advance, rev, seed_branches
from tests.serving import seed_pipeline, seed_review_round


def approve(api: httpx.Client, uid: str = "feature/2") -> httpx.Response:
    return api.post(f"/api/units/{uid}/actions/approve", json={})


def listed(api: httpx.Client, uid: str = "feature/2") -> dict[str, object]:
    actions = api.get(f"/api/units/{uid}").json()["actions"]
    return next(a for a in actions if a["name"] == "approve")


def test_approve_records_an_approved_decision_for_the_current_round_at_the_head(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    seed_review_round(inst, "feature/2", 3)

    answer = approve(api)

    assert answer.status_code == 200
    [decision] = stored_decisions(inst, "feature/2")
    assert (decision["round"], decision["decision"]) == (3, "approve")
    assert decision["head"] == rev(repo, "spec/feature/2")
    assert answer.json()["message"]


def test_the_head_is_the_one_the_branch_has_when_approve_is_chosen(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    moved = advance(repo, "spec/feature/2", "more.py", "more\n")

    approve(api)

    [decision] = stored_decisions(inst, "feature/2")
    assert decision["head"] == moved


def test_the_decision_reads_back_with_its_head_in_the_review(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)

    approve(api)

    [decision] = api.get("/api/units/feature/2/review").json()["decisions"]
    assert decision["head"] == rev(repo, "spec/feature/2")


def test_a_decision_recorded_before_heads_reads_as_it_did(inst: Installation) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    write_an_old_decision(inst, "feature/2", 1)

    with start_server(inst) as server, httpx.Client(base_url=server.url) as client:
        [decision] = client.get("/api/units/feature/2/review").json()["decisions"]

    assert (decision["round"], decision["decision"], decision["summary"]) == (
        1,
        "request_changes",
        "Needs a test",
    )
    assert "head" in decision
    assert not decision["head"]


def test_approve_merges_nothing_pushes_nothing_and_leaves_the_host_alone(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    remote = give_a_remote(repo)
    host = watch_the_host()
    branches = rev(repo, "spec/feature/2"), rev(repo, "main")

    answer = approve(api)

    assert answer.status_code == 200
    assert host.requests == []
    assert refs(remote) == ""
    assert (rev(repo, "spec/feature/2"), rev(repo, "main")) == branches
    assert api.get("/api/units/feature/2").json()["state"] == "in_review"


def test_a_unit_with_no_pull_request_cannot_be_approved(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    answer = approve(api, "feature/6")

    assert answer.status_code == 409
    assert "no pull request" in answer.json()["detail"]
    assert stored_decisions(inst, "feature/6") == []
    action = listed(api, "feature/6")
    assert action["enabled"] is False
    assert action["reason"] == answer.json()["detail"]


def test_a_unit_with_no_head_cannot_be_approved(inst: Installation, api: httpx.Client) -> None:
    seed_pipeline(inst)
    without_a_branch(inst)

    answer = approve(api)

    assert answer.status_code == 409
    assert "head" in answer.json()["detail"]
    assert stored_decisions(inst, "feature/2") == []
    action = listed(api)
    assert action["enabled"] is False
    assert action["reason"] == answer.json()["detail"]


def test_a_round_that_already_has_a_decision_cannot_be_approved(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    api.put(
        "/api/units/feature/2/review/decision",
        json={"decision": "request_changes", "summary": "Needs a test"},
    )
    before = stored_decisions(inst, "feature/2")

    answer = approve(api)

    assert answer.status_code == 409
    assert "round 1" in answer.json()["detail"]
    assert stored_decisions(inst, "feature/2") == before
    assert listed(api)["enabled"] is False


def test_a_unit_that_can_be_approved_lists_the_action_as_open(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    assert listed(api) == {"name": "approve", "enabled": True, "reason": ""}


def test_the_next_round_can_be_approved_after_the_last_was_decided(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    seed_review_round(inst, "feature/2", 1)
    approve(api)
    seed_review_round(inst, "feature/2", 2)

    answer = approve(api)

    assert answer.status_code == 200
    assert [d["round"] for d in stored_decisions(inst, "feature/2")] == [1, 2]
