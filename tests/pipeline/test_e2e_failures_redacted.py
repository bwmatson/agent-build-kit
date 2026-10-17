"""A failure line is redacted before it is shortened, in the listing, the result and
the saved feedback."""

from pathlib import Path

from agent_build_kit.pipeline.e2e import E2eResult
from tests.e2e_failure_fakes import gate, run_failing_e2e, run_returning
from tests.redaction_fakes import NAME, SECRET, known

REPLACED = f"[redacted:{NAME}]"
# The value starts a few characters before the fixed length, so a cut first leaves
# half of it.
LINE = "RuntimeError: " + "x" * 480 + SECRET + "y" * 200
OUTPUT = f"=== short test summary info ===\nFAILED tests/t.py::test_a - {LINE}\n1 failed in 1s\n"


def _run(root: Path) -> tuple[E2eResult, str]:
    root.mkdir()
    session = gate(root, run_returning(OUTPUT), root=root)
    with known():
        _, snapshot = session.run(cwd=root)
    assert session.result is not None
    return session.result, snapshot


def test_the_listing_and_the_result_hold_the_replacement(tmp_path: Path) -> None:
    result, snapshot = _run(tmp_path / "run")

    (failure,) = result.failures
    assert REPLACED[:5] in failure.line, "the cut falls inside the replacement"
    for text in (failure.line, snapshot, result.model_dump_json()):
        assert SECRET[:8] not in text
        assert SECRET[-8:] not in text
    assert REPLACED[:5] in snapshot.split("<details>")[0]


def test_the_saved_feedback_holds_the_replacement(tmp_path: Path) -> None:
    _, snapshot = _run(tmp_path / "run")
    (tmp_path / "unit").mkdir()

    with known():
        feedback, _ = run_failing_e2e(tmp_path / "unit", snapshot)

    assert "`tests/t.py::test_a` - RuntimeError: " in feedback
    assert REPLACED in feedback
    assert SECRET[:8] not in feedback
