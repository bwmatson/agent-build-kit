"""The Claude Code runtime's default models: `sonnet` builds and reworks, `opus`
judges both, so neither review is made by the model that wrote the work."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.settings import settings

ROOT = Path(__file__).resolve().parent.parent


def activate(root: Path, text: str) -> None:
    path = root / "abk.yaml"
    path.write_text(text)
    config.activate(config.load(path), root)


def test_a_flat_block_naming_one_role_leaves_the_others_the_new_defaults(tmp_path: Path) -> None:
    activate(tmp_path, "models:\n  implement: haiku\n")

    models = config.models()

    assert models.implement == "haiku"
    assert (models.rework, models.review, models.rework_review) == ("sonnet", "opus", "opus")


def test_a_machine_override_wins_and_the_other_roles_take_the_new_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(tmp_path, "runtime: claude_code\n")
    monkeypatch.setattr(settings, "review_model", "this-machine")

    models = config.models()

    assert models.review == "this-machine"
    assert (models.implement, models.rework, models.rework_review) == ("sonnet", "sonnet", "opus")


def test_the_reviews_default_to_a_model_other_than_the_author(tmp_path: Path) -> None:
    activate(tmp_path, "runtime: claude_code\n")

    models = config.models()

    assert models.review != models.implement
    assert models.rework_review != models.rework


@pytest.mark.parametrize("document", ["docs/configuration.md", "docs/agent-runtimes.md"])
def test_no_document_states_the_earlier_defaults(document: str) -> None:
    text = (ROOT / document).read_text()

    assert "rework_review: fable" not in text
    assert "implement: opus" not in text
