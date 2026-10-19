"""`abk retire` closes the unit's open pull request with the reason, keeps a close the host
refused for the next pass, and deletes the unit's thread (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.wiring import build_close_pr
from tests.forges.stand_in import lookup
from tests.retire_scene import Scene, scene  # noqa: F401

UNIT = "feature/3"


def in_review(scene: Scene) -> None:  # noqa: F811
    scene.add(UNIT, "in_review", pr=4)
    scene.built_elsewhere(UNIT)


def test_the_reason_is_posted_and_the_pull_request_closed(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    in_review(scene)

    code, _ = scene.retire(capsys, UNIT, "--reason", "superseded by feature/9")

    assert code == 0
    assert scene.unit(UNIT).state == "retired"
    assert scene.host.closed == [4]
    assert scene.host.calls == [("comment", 4), ("close", 4)]
    assert "superseded by feature/9" in scene.host.comments[0]


def test_a_close_the_host_refuses_is_kept_and_repeated_by_a_pass(
    scene: Scene,  # noqa: F811
    capsys,
) -> None:
    in_review(scene)
    scene.host.close_error = "502 Bad Gateway"

    code, out = scene.retire(capsys, UNIT, "--reason", "superseded")

    assert code == 1
    assert "#4" in out
    kept = scene.unit(UNIT)
    assert kept.state == "retired"
    assert kept.close_pending is not None and kept.close_pending.pr == 4
    assert "superseded" in kept.close_pending.reason

    scene.host.close_error = ""
    cli.retry_closes(scene.store, close_pr=build_close_pr(for_repo=lookup(scene.host)))

    assert scene.host.closed == [4]
    assert scene.unit(UNIT).close_pending is None


def test_a_unit_with_no_pull_request_calls_no_forge(scene: Scene, capsys) -> None:  # noqa: F811
    scene.add(UNIT)
    scene.built_elsewhere(UNIT)

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert scene.host.calls == [] and scene.untouched()


def test_the_unit_s_thread_is_deleted(scene: Scene, capsys) -> None:  # noqa: F811
    in_review(scene)
    scene.thread(UNIT)
    assert scene.has_thread(UNIT)

    code, _ = scene.retire(capsys, UNIT)

    assert code == 0
    assert not scene.has_thread(UNIT)
