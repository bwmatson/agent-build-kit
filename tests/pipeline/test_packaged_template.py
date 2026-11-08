"""Reading a packaged prompt text from the templates folder."""

from agent_build_kit.pipeline.determinism_guidance import determinism_guidance
from agent_build_kit.pipeline.packaged_template import packaged_template
from agent_build_kit.pipeline.reuse_guidance import reuse_guidance
from agent_build_kit.pipeline.standards_guidance import standards_guidance


def test_a_template_is_read_without_surrounding_whitespace() -> None:
    text = packaged_template("test-standards.md")

    assert text
    assert text == text.strip()


def test_each_guidance_is_the_text_of_its_template() -> None:
    assert standards_guidance() == packaged_template("test-standards.md")
    assert determinism_guidance() == packaged_template("determinism-guidance.md")
    assert reuse_guidance("tests") == packaged_template("reuse-guidance-tests.md")
