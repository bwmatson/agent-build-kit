"""Unit actions: requeue, hold, release and approve go through the CLI's own code, under
the unit store's lock, with the real hooks; the log names the UI as the actor; and the
CLI's refusal comes back as the reason (spec: web-ui, Actions go through the CLI's code)."""

from __future__ import annotations

import json
import threading

import httpx
import pytest

from agent_build_kit.cli import main
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL, state_path
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED
from tests.serving import EXPECTED, seed_pipeline


@pytest.fixture
def pipeline(inst: Installation, api: httpx.Client) -> httpx.Client:
    seed_pipeline(inst)
    return api


def act(client: httpx.Client, uid: str, action: str, **body: str) -> httpx.Response:
    return client.post(f"/api/units/{uid}/actions/{action}", json=body)


def test_requeue_of_a_failed_unit_does_what_the_cli_does(
    inst: Installation, pipeline: httpx.Client
) -> None:
    answer = act(pipeline, "feature/6", "requeue")

    assert answer.status_code == 200
    after = UnitStore(inst.state_dir / "units.json").get("feature/6")
    assert (after.state, after.cause) == ("planned", Cause.REQUEUED)
    assert "requeued" in after.history[-1]["note"]


def test_a_requeue_here_leaves_the_unit_as_the_cli_does(
    inst: Installation, pipeline: httpx.Client
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    act(pipeline, "feature/6", "requeue")
    via_ui = store.get("feature/6")
    store.set_state("feature/6", FAILED, note="tier 1 failed", cause=Cause.FAILED)

    assert main(["requeue", "feature/6"]) == 0

    via_cli = store.get("feature/6")
    assert (via_ui.state, via_ui.cause, via_ui.feedback) == (
        via_cli.state,
        via_cli.cause,
        via_cli.feedback,
    )


@pytest.mark.parametrize("mode", ["restart", "rework", "resume"])
def test_the_requeue_modes_are_the_clis(
    inst: Installation, pipeline: httpx.Client, mode: str
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    store.set_feedback("feature/6", "tier 1 failed: a type error")

    answer = act(pipeline, "feature/6", "requeue", mode=mode)

    assert answer.status_code == 200
    after = store.get("feature/6")
    assert after.state == "planned"
    assert (after.feedback == "") is (mode == "restart")


def test_an_action_runs_the_real_hooks(inst: Installation, pipeline: httpx.Client) -> None:
    # The CLI's store rewrites the graph page on every change; a bare store would not.
    inst.graph_page.unlink(missing_ok=True)

    act(pipeline, "feature/6", "requeue")

    assert inst.graph_page.exists()


def test_an_action_waits_for_the_stores_lock(inst: Installation, api: httpx.Client) -> None:
    seed_pipeline(inst)
    lock = inst.state_dir / "units.json.lock"
    held, release = threading.Event(), threading.Event()

    def hold_lock() -> None:
        with file_lock(lock):
            held.set()
            release.wait(10)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    held.wait(5)
    try:
        with pytest.raises(httpx.TimeoutException):
            api.post("/api/units/feature/6/actions/requeue", json={}, timeout=1)
    finally:
        release.set()
        holder.join()


def test_the_log_names_the_ui_as_the_actor(
    pipeline: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    act(pipeline, "feature/6", "requeue")

    lines = [line for line in capsys.readouterr().out.splitlines() if "feature/6" in line]
    assert any("requeue" in line and "the web UI" in line for line in lines)


def test_an_invalid_mode_is_refused_before_anything_is_logged(
    pipeline: httpx.Client, capsys: pytest.CaptureFixture[str]
) -> None:
    answer = act(pipeline, "feature/6", "requeue", mode="sideways")

    assert answer.status_code == 422
    assert "chosen by" not in capsys.readouterr().out


def test_a_hold_is_delivered_to_the_units_thread_as_the_poller_would(
    pipeline: httpx.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_build_kit.cli import pipeline as cli_pipeline

    delivered: list[tuple[str, str]] = []

    def resume(inst, unit, kind, **kwargs):  # noqa: ANN001, ANN003, ANN202
        delivered.append((unit.id, kind))
        return object()

    monkeypatch.setattr(cli_pipeline, "resume_thread", resume)

    answer = act(pipeline, "feature/2", "hold")

    assert answer.status_code == 200
    assert delivered == [("feature/2", "hold")]


def test_a_hold_waits_out_a_unit_being_built(inst: Installation, pipeline: httpx.Client) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    before = store.get("feature/2")
    claim = build_claim(inst.state_dir / "locks")

    with claim(before):
        answer = act(pipeline, "feature/2", "hold")

    assert answer.status_code == 409
    assert "is being built" in answer.json()["detail"]
    assert store.get("feature/2") == before


def test_a_release_is_refused_while_the_pull_request_carries_the_hold_label(
    inst: Installation, pipeline: httpx.Client
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    act(pipeline, "feature/2", "hold")
    held = store.get("feature/2")
    state_path(inst.state_dir, held.repo).write_text(
        json.dumps({str(held.pr): {"labels": [HOLD_LABEL]}})
    )

    answer = act(pipeline, "feature/2", "release")

    assert answer.status_code == 409
    assert HOLD_LABEL in answer.json()["detail"]
    assert store.get("feature/2") == held
    listed = {a["name"]: a for a in pipeline.get("/api/units/feature/2").json()["actions"]}
    assert not listed["release"]["enabled"]


@pytest.mark.parametrize("uid", ["feature/2", "feature/7", "feature/1", "feature/9"])
def test_requeue_is_refused_with_the_clis_reason(
    inst: Installation,
    pipeline: httpx.Client,
    uid: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    before = store.get(uid)
    assert main(["requeue", uid]) == 1
    reason = capsys.readouterr().out.strip()

    answer = act(pipeline, uid, "requeue")

    assert answer.status_code == 409
    assert answer.json()["detail"] == reason
    assert f"{uid} is {EXPECTED[uid][0]}" in reason
    assert store.get(uid) == before


def test_rework_without_a_saved_failure_is_refused_with_the_clis_reason(
    pipeline: httpx.Client,
) -> None:
    answer = act(pipeline, "feature/6", "requeue", mode="rework")

    assert answer.status_code == 409
    assert "no saved failure to rework from" in answer.json()["detail"]


def test_an_unknown_unit_or_action_is_not_found(pipeline: httpx.Client) -> None:
    assert act(pipeline, "feature/99", "requeue").status_code == 404
    assert act(pipeline, "feature/6", "delete").status_code == 404


def test_hold_and_release_move_a_unit_in_review_as_the_labels_do(
    inst: Installation, pipeline: httpx.Client
) -> None:
    store = UnitStore(inst.state_dir / "units.json")

    held = act(pipeline, "feature/2", "hold")
    after_hold = store.get("feature/2")
    released = act(pipeline, "feature/2", "release")
    after_release = store.get("feature/2")

    assert held.status_code == released.status_code == 200
    assert (after_hold.state, after_hold.cause) == ("held", Cause.REVIEWER_HOLD)
    assert (after_release.state, after_release.cause) == ("in_review", Cause.RELEASED)


@pytest.mark.parametrize("action", ["requeue", "hold", "release", "approve"])
def test_every_action_is_refused_for_a_running_unit(
    inst: Installation, pipeline: httpx.Client, action: str
) -> None:
    store = UnitStore(inst.state_dir / "units.json")
    before = store.get("feature/7")

    answer = act(pipeline, "feature/7", action)

    assert answer.status_code == 409
    assert answer.json()["detail"]
    assert store.get("feature/7") == before


def test_a_unit_reports_which_actions_are_open_and_why_not(pipeline: httpx.Client) -> None:
    running = {a["name"]: a for a in pipeline.get("/api/units/feature/7").json()["actions"]}
    failed = {a["name"]: a for a in pipeline.get("/api/units/feature/6").json()["actions"]}

    assert set(running) == set(failed) == {"requeue", "hold", "release", "approve"}
    assert not any(a["enabled"] for a in running.values())
    assert all(a["reason"] for a in running.values())
    assert failed["requeue"]["enabled"] is True
    assert failed["requeue"]["reason"] == ""
    assert "feature/7 is running" in running["requeue"]["reason"]
