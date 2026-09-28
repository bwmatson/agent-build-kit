"""The research step: one model call per language, its text written with a
dated header."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from agent_build_kit.init.research import ALLOWED_TOOLS, SECTIONS, build_prompt, research

TODAY = date(2030, 1, 2)


def capture(text: str):
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(argv)
        return text

    return run, calls


def test_the_call_is_read_only_with_web_access(tmp_path: Path) -> None:
    run, calls = capture("## Formatting\n\n- rule\n\n## Sources\n\n- https://example.invalid\n")

    research(
        "python", built_in="seed text", output=tmp_path / "python.md", run_claude=run, today=TODAY
    )

    [argv] = calls
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--allowedTools") + 1] == ALLOWED_TOOLS
    assert argv[argv.index("--output-format") + 1] == "text"
    assert "Write" not in ALLOWED_TOOLS.split()


def test_a_seeded_prompt_asks_for_validation_against_today() -> None:
    prompt = build_prompt("python", built_in="- ruff ≥ 0.16", today=TODAY)

    assert "as of 2030-01-02" in prompt
    assert "keep, amend or drop" in prompt
    assert "Keep this structure" in prompt
    assert "- ruff ≥ 0.16" in prompt
    for section in SECTIONS:
        assert section in prompt


def test_an_unknown_language_asks_for_the_same_structure() -> None:
    prompt = build_prompt("rust", built_in=None, today=TODAY)

    assert "same structure" in prompt
    assert "Seed:" not in prompt
    assert "rust" in prompt


def test_output_is_the_models_text_under_a_dated_header(tmp_path: Path) -> None:
    body = "## Formatting\n\n- rule one\n\n## Sources\n\n- https://example.invalid/ruff\n"
    run, _ = capture(body)

    path = research(
        "python",
        built_in="seed",
        output=tmp_path / "docs" / "python.md",
        run_claude=run,
        today=TODAY,
    )

    text = path.read_text()
    assert text.startswith("# Python: tooling recommendations\n")
    assert "2030-01-02" in text
    assert text.endswith(body)
    assert text.count("## Sources") == 1


def test_a_missing_sources_section_is_appended(tmp_path: Path) -> None:
    run, _ = capture("## Formatting\n\n- rule one\n")

    path = research(
        "python", built_in=None, output=tmp_path / "python.md", run_claude=run, today=TODAY
    )

    text = path.read_text()
    assert "## Sources" in text
    assert "did not list its sources" in text
    assert "no built-in seed" in text
