"""The mode of the requeue when a wait ends follows the unit's record, and
`global_limits.wait_end_requeue` overrides it or turns the requeue off."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.config import LimitsConfig
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from tests.wait_end_support import CHILD, mode_chosen, pipeline, save_failure

CHECKS = [FeedbackSource.E2E, FeedbackSource.UNIT_TEST]
ENVIRONMENT = [
    Cause.TOOLCHAIN,
    Cause.ENVIRONMENT,
    Cause.HOST_UNAVAILABLE,
    Cause.NETWORK_UNAVAILABLE,
    Cause.SERVICE_UNAVAILABLE,
]
OTHER_SOURCES = [FeedbackSource.REVIEW, FeedbackSource.CI, FeedbackSource.CONFLICT]


@pytest.mark.parametrize("source", CHECKS)
def test_a_saved_check_failure_with_feedback_is_a_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: FeedbackSource
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    save_failure(pipe, feedback="3 tests failed", source=source)

    assert mode_chosen(pipe) == "rework"


@pytest.mark.parametrize("cause", ENVIRONMENT)
def test_an_environmental_cause_is_a_resume_even_with_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: Cause
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    save_failure(pipe, feedback="3 tests failed", source=FeedbackSource.E2E, cause=cause)

    assert mode_chosen(pipe) == "resume"


def test_no_saved_failure_is_a_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()

    assert mode_chosen(pipe) == "resume"


@pytest.mark.parametrize("source", OTHER_SOURCES)
def test_a_review_ci_or_conflict_failure_is_a_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: FeedbackSource
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    save_failure(pipe, feedback="please rename it", source=source)

    assert mode_chosen(pipe) == "resume"


def test_a_persons_note_stays_in_the_guidance_and_does_not_make_a_resume_a_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    save_failure(pipe, guidance="start from the date")

    assert mode_chosen(pipe) == "resume"
    assert pipe.store.get(CHILD).guidance == "start from the date"


def test_a_persons_note_is_kept_on_a_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    save_failure(
        pipe, feedback="3 tests failed", source=FeedbackSource.E2E, guidance="start from the date"
    )

    assert mode_chosen(pipe) == "rework"
    assert pipe.store.get(CHILD).guidance == "start from the date"
    assert pipe.store.get(CHILD).feedback == "3 tests failed"


def test_a_unit_is_never_restarted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipe = pipeline(tmp_path, monkeypatch)
    pipe.waiting_failed()
    save_failure(pipe, feedback="3 tests failed", source=FeedbackSource.E2E)

    assert mode_chosen(pipe) != "restart"
    assert pipe.store.get(CHILD).feedback == "3 tests failed"


@pytest.mark.parametrize("setting", ["resume", "rework"])
def test_the_setting_forces_its_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, wait_end_requeue=setting)
    pipe.waiting_failed()
    save_failure(
        pipe,
        feedback="3 tests failed" if setting == "resume" else "toolchain missing",
        source=FeedbackSource.E2E if setting == "resume" else FeedbackSource.CI,
        cause=Cause.FAILED if setting == "resume" else Cause.TOOLCHAIN,
    )

    assert mode_chosen(pipe) == setting


def test_a_forced_rework_with_nothing_saved_falls_back_to_a_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, wait_end_requeue="rework")
    pipe.waiting_failed()

    assert mode_chosen(pipe) == "resume"


def test_off_records_nothing_and_requeues_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipe = pipeline(tmp_path, monkeypatch, wait_end_requeue="off")
    pipe.waiting_failed()

    pipe.pass_()
    assert pipe.store.get(CHILD).waited_on == ()
    pipe.merge()
    pipe.passes(2)

    assert pipe.host.deliveries == []
    assert pipe.store.get(CHILD).state == "failed"
    assert pipe.store.get(CHILD).waited_on == ()


def test_an_unknown_value_is_refused_when_the_config_loads_and_the_allowed_ones_are_named() -> None:
    with pytest.raises(ValidationError) as refused:
        LimitsConfig.model_validate({"wait_end_requeue": "sometimes"})

    said = str(refused.value)
    assert all(value in said for value in ("auto", "resume", "rework", "off"))


def test_the_default_is_auto() -> None:
    assert LimitsConfig().model_dump()["wait_end_requeue"] == "auto"
