"""The walk of a unit through review over `abk serve`'s API, for any runtime.

`walk_unit_through_review` builds the `add-marker` unit with the scratch installation's runtime,
then drives what a person sees of it: the pipeline and the unit's page, its recorded history with
tool calls, a live step with the composer disabled, a chat turn once the step ends, the unit
resuming from its node after the lease is released, a new session, and a requeue. It carries no
runtime tag: the test that calls it says which runtime it drives, and the live-test drift check
reads the tag from that test.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED
from agent_build_kit.pipeline.workspaces import worktree_path
from tests.agent_home import assert_unit_session_listed
from tests.chat_serving import events_of, turn
from tests.marker_scratch import BRANCH, CHANGE, UNIT_ID, Scratch, thread_next
from tests.scratch_tick import commits_on_unit_branch, run_tick
from tests.waiting import wait_for

UNIT_URL = f"/api/units/{CHANGE}/1"
COMMENT = "Please add a one-line docstring to `marker()` saying what it returns."
SECOND_COMMENT = "Please also mention in the docstring that the value is a constant."
SAY_OK = "Reply with the single word ok. Do not use any tool or change any file."
# A turn on a real agent takes as long as the agent takes.
WAIT = 900


def agent_state(api: httpx.Client, tab: str) -> dict[str, Any]:
    answer = api.get(f"{UNIT_URL}/agent", params={"tab": tab})
    assert answer.status_code == 200, answer.text
    return answer.json()


def finished(events: list[dict[str, Any]]) -> bool:
    return any(e["type"] == "RUN_FINISHED" for e in events)


def wait_for_streaming(api: httpx.Client, tab: str) -> dict[str, Any]:
    wait_for(
        lambda: agent_state(api, tab)["state"] == "streaming",
        what="the unit's step to show as streaming",
        timeout=WAIT,
    )
    return agent_state(api, tab)


def walk_unit_through_review(scratch: Scratch, api: httpx.Client, runtime: str) -> None:
    """Build the unit in `scratch` with `runtime` and walk it through review over `api`."""
    built = run_tick(scratch)
    assert built.returncode == 0, built.output
    commits_on_unit_branch(scratch, BRANCH, built)
    assert thread_next(scratch.state) == (Node.AWAIT_REVIEW,), built.output
    if runtime == "acp":
        # Chatting and rework resume the build's session: the agent must list it, or say why not.
        cwd = worktree_path(
            scratch.app, BRANCH, scratch.installation.worktree_root, name=scratch.app.name
        )
        assert_unit_session_listed(scratch.state, UNIT_ID, scratch.command, cwd)
    # The server resolves the ticks' installation: it reports the agent that built the unit.
    recorded = api.get(f"{UNIT_URL}/agent").json()["session"]
    assert recorded is not None and recorded["runtime"] == runtime, recorded

    # The pipeline and the unit's page.
    listed = api.get("/api/pipeline").json()["units"]
    assert [u["id"] for u in listed] == [UNIT_ID]
    page = api.get(UNIT_URL).json()
    assert (page["state"], page["pr"]) == ("in_review", 7)
    actions = {a["name"]: a for a in page["actions"]}
    assert not actions["requeue"]["enabled"] and actions["requeue"]["reason"]
    assert api.get(f"{UNIT_URL}/logs").json()["runs"], "the build's run logs were not listed"

    # The build's recorded history carries its tool calls.
    with api.stream("GET", f"{UNIT_URL}/agent/events", params={"tab": "history"}) as response:
        snapshot = next(events_of(response))
    assert snapshot["type"] == "MESSAGES_SNAPSHOT"
    assert any(m.get("toolCalls") for m in snapshot["messages"]), snapshot
    assert agent_state(api, "history")["composer"]["enabled"] is True

    # A rework step streams live, and takes no input while it runs.
    scratch.host.add_review(7, "COMMENTED", "", inline=("src/app/marker.py", 1, COMMENT))
    with ThreadPoolExecutor(max_workers=1) as ticks:
        reworking = ticks.submit(run_tick, scratch)
        try:
            live = wait_for_streaming(api, "watcher")
            assert live["composer"]["enabled"] is False and live["composer"]["reason"], live
            refused = api.post(f"{UNIT_URL}/chat", json={"tab": "watcher", "prompt": SAY_OK})
            assert refused.status_code == 409, refused.text
            with api.stream(
                "GET", f"{UNIT_URL}/agent/events", params={"tab": "watcher"}
            ) as response:
                seen: list[str] = []
                for event in events_of(response):
                    seen.append(event["type"])
                    # The stream stays open for later runs: leave it once this one has ended.
                    if event["type"] in ("RUN_FINISHED", "RUN_ERROR"):
                        break
            assert "RUN_STARTED" in seen and seen[-1] == "RUN_FINISHED", seen
        finally:
            reworked = reworking.result(timeout=WAIT)
    assert reworked.returncode == 0, reworked.output

    # Once the step ends the session is chattable; a turn holds the lease.
    after = agent_state(api, "chatter")
    assert after["composer"]["enabled"] is True, after
    said = turn(api, f"{UNIT_URL}/chat", {"tab": "chatter", "prompt": SAY_OK}, timeout=WAIT)
    assert finished(said), said
    assert agent_state(api, "chatter")["attached_by"] == "tab:chatter"

    # While the lease is held a review comment is not acted on; released, the unit resumes
    # from the node it was parked at and reworks.
    before = commits_on_unit_branch(scratch, BRANCH, reworked)
    scratch.host.add_review(7, "COMMENTED", "", inline=("src/app/marker.py", 1, SECOND_COMMENT))
    leased = run_tick(scratch)
    assert leased.returncode == 0, leased.output
    assert commits_on_unit_branch(scratch, BRANCH, leased) == before, (
        f"a leased unit was reworked\n{leased.output}"
    )
    assert api.delete(f"{UNIT_URL}/lease", params={"tab": "chatter"}).status_code == 204
    resumed = run_tick(scratch)
    assert resumed.returncode == 0, resumed.output
    assert len(commits_on_unit_branch(scratch, BRANCH, resumed)) > len(before), resumed.output
    assert thread_next(scratch.state) == (Node.AWAIT_REVIEW,), resumed.output

    # A new session on the unit's runtime, in the app's own checkout.
    started = turn(
        api,
        "/api/sessions",
        {"runtime": runtime, "repo": "app", "tab": "new-session", "prompt": SAY_OK},
        timeout=WAIT,
    )
    assert finished(started), started

    # A failed unit is requeued from its page.
    UnitStore(scratch.state / "units.json").set_state(UNIT_ID, FAILED, note="failed by hand")
    assert {a["name"]: a for a in api.get(UNIT_URL).json()["actions"]}["requeue"]["enabled"]
    requeued = api.post(f"{UNIT_URL}/actions/requeue", json={})
    assert requeued.status_code == 200, requeued.text
    after_requeue = api.get(UNIT_URL).json()
    # The unit's thread is parked, so the requeue resumes it rather than planning it afresh.
    assert (after_requeue["state"], after_requeue["cause"]) == ("running", Cause.REQUEUED.value)
    assert thread_next(scratch.state) == (Node.PREPARE,)
