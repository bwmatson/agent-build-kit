"""A person's note reaches every group's prompts in a stubbed build, and is cleared and handed to
review once, after the last group (spec: per-group-commits)."""

from __future__ import annotations

from pathlib import Path

from tests.graph.stub_loop_fakes import stubbed_build, with_three_groups
from tests.graph.test_build_path import build
from tests.graph.test_joined_unit_builds import tasks

UNIT = "add-marker/1"
NOTE = "keep the marker name short"


def test_the_note_is_in_all_six_prompts_and_is_cleared_and_asked_once(tmp_path: Path) -> None:
    stubbed_build()
    tasks(tmp_path, "add-marker", (1, 2, 3))
    recorder = with_three_groups(tmp_path)
    recorder.store.set_guidance(UNIT, NOTE)

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    built = recorder.prompts[:6]
    assert len(built) == 6
    assert all(NOTE in prompt for prompt in built)
    assert recorder.store.get(UNIT).guidance == ""
    assert "\n".join(recorder.contexts).count(NOTE) == 1, "review is told the note once"
