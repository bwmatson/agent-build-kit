"""The planner prompt says the reply's ids are labels and the program assigns the ids
(spec: unit-ids-come-from-the-groups)."""

from __future__ import annotations

import re

from agent_build_kit.pipeline.planner import build_prompt
from tests.prompt_text import flat


def test_the_reply_shape_shows_a_label_and_not_a_change_number() -> None:
    prompt = build_prompt({}, [])

    assert '"id": "<label>"' in prompt
    assert '"<change>/<n>"' not in prompt


def test_the_prompt_says_the_program_assigns_the_ids_from_the_groups() -> None:
    text = flat(build_prompt({}, [])).lower()

    assert re.search(r"program assigns[^.]*\bid", text)
    assert re.search(r"label[^.]*(unique|own)", text)


def test_the_prompt_says_a_unit_in_flight_is_referred_to_by_the_id_shown() -> None:
    text = flat(build_prompt({}, [])).lower()

    assert re.search(r"in flight[^.]*referred to by the id shown|by the id shown", text)
    assert "depends_on" in text and "needs_less_urgent" in text
    assert re.search(r"label[^.]*depends_on[^.]*needs_less_urgent", text)
