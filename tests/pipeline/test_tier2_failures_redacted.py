"""A failure line is redacted before it is shortened, in the listing, the result and
the saved feedback."""

from pathlib import Path

from agent_build_kit.pipeline.tier2 import Tier2Result
from tests.redaction_fakes import NAME, SECRET, known
from tests.tier2_failure_fakes import feedback_after_failing_tier2, gate, run_returning

REPLACED = f"[redacted:{NAME}]"
# The value starts a few characters before the fixed length, so a cut first leaves
# half of it.
LINE = "RuntimeError: " + "x" * 480 + SECRET + "y" * 200
OUTPUT = f"=== short test summary info ===\nFAILED tests/t.py::test_a - {LINE}\n1 failed in 1s\n"


def _run(root: Path) -> tuple[Tier2Result, str]:
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    session = gate(root, run_returning(OUTPUT))
    with known():
        _, snapshot = session.run(cwd=root)
    assert session.result is not None
    return session.result, snapshot


def test_the_listing_and_the_result_hold_the_replacement(tmp_path: Path) -> None:
    result, snapshot = _run(tmp_path / "run")

    (failure,) = result.failures
    assert REPLACED in failure.line
    for text in (failure.line, snapshot, result.model_dump_json()):
        assert SECRET[:8] not in text
        assert SECRET[-8:] not in text
    assert REPLACED in snapshot.split("<details>")[0]


def test_the_saved_feedback_holds_the_replacement(tmp_path: Path) -> None:
    _, snapshot = _run(tmp_path / "run")
    (tmp_path / "unit").mkdir()

    with known():
        feedback = feedback_after_failing_tier2(tmp_path / "unit", snapshot)

    assert "`tests/t.py::test_a` - RuntimeError: " in feedback
    assert REPLACED in feedback
    assert SECRET[:8] not in feedback
