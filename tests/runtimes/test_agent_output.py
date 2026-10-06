"""What the agent tools' own fields mean, read in one adapter and pinned against recordings.

The fixtures under `tests/fixtures/external/claude/` and `.../acp/` hold the
closing events and tool call updates with the tool version noted; a change in
either tool's shape or wording fails here.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from acp.schema import ToolCallProgress

from agent_build_kit.pipeline.claude_stream import ResultEvent, own_words, result_event
from agent_build_kit.runtimes.acp_output import denied_call
from agent_build_kit.runtimes.claude_output import agent_failure

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external"


def closing_event(name: str) -> tuple[ResultEvent | None, str]:
    """A recorded run as the runtime sees it: its closing event and the CLI's own words."""
    _, _, rest = (FIXTURES / "claude" / f"{name}.txt").read_text().partition("--- stdout\n")
    stdout, _, stderr = rest.partition("--- stderr\n")
    return result_event(stdout), f"{own_words(stdout)}\n{stderr}".strip()


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("result_success", "none"),
        ("result_rate_limited_structured", "rate_limited"),
        ("result_rate_limited_text_only", "rate_limited"),
        ("result_session_gone", "session_unavailable"),
        ("result_generic_error", "other"),
    ],
)
def test_a_recorded_closing_event_is_classified(name: str, kind: str) -> None:
    event, text = closing_event(name)

    assert agent_failure(event, text).kind == kind


def test_a_rate_limit_is_read_from_the_status_before_any_prose() -> None:
    event, text = closing_event("result_rate_limited_structured")

    assert "limit" not in text.lower()
    assert "429" not in text
    assert agent_failure(event, text).kind == "rate_limited"


def test_a_text_only_rate_limit_says_when_it_lifts() -> None:
    event, text = closing_event("result_rate_limited_text_only")

    assert agent_failure(event, text).resets_at == datetime.fromtimestamp(1919763200, UTC)


def test_a_structured_rate_limit_that_says_no_time_has_none() -> None:
    event, text = closing_event("result_rate_limited_structured")

    assert agent_failure(event, text).resets_at is None


def test_an_unlisted_subtype_is_not_a_success() -> None:
    event, text = closing_event("result_success")
    assert event is not None
    odd = event.model_copy(update={"subtype": "success_with_warnings"})

    assert agent_failure(odd, text).kind == "other"


def test_an_error_flagged_success_subtype_is_not_a_success() -> None:
    event, text = closing_event("result_generic_error")
    assert event is not None
    flagged = event.model_copy(update={"subtype": "success"})

    assert agent_failure(flagged, text).kind == "other"


def test_a_run_with_no_closing_event_is_read_by_its_words() -> None:
    assert agent_failure(None, "Claude AI usage limit reached|1919763200").kind == "rate_limited"
    assert agent_failure(None, "segmentation fault").kind == "other"


def recorded_update(name: str) -> ToolCallProgress:
    return ToolCallProgress.model_validate(
        json.loads((FIXTURES / "acp" / f"{name}.json").read_text())
    )


@pytest.mark.parametrize(
    ("name", "denied"),
    [
        ("update_denied", True),
        ("update_allowed", False),
        ("update_errored", False),
    ],
)
def test_a_recorded_update_is_classified_by_status_and_error(name: str, denied: bool) -> None:
    assert denied_call(recorded_update(name)) is denied


def test_the_phrases_decide_only_when_the_structured_fields_are_absent() -> None:
    assert denied_call(recorded_update("update_denied_unstructured")) is True
    assert denied_call(recorded_update("update_errored_unstructured")) is False


def test_a_denial_phrase_in_a_successful_call_s_output_is_not_a_denial() -> None:
    update = recorded_update("update_allowed")

    assert "denied" in json.dumps(update.raw_output)
    assert denied_call(update) is False
