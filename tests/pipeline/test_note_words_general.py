"""A note with an id is handed to the rework tagged, anchored or not, so a reply can find it."""

from __future__ import annotations

import json

from agent_build_kit.forges import ReviewNote
from agent_build_kit.pipeline.events import note_words
from agent_build_kit.pipeline.pr_replies import parse_answer
from agent_build_kit.pipeline.stack_runner import COMMENT_LINE


def test_every_note_with_an_id_is_tagged_and_a_reply_finds_it() -> None:
    general = ReviewNote(id="660.1", body="Please make one_pass the default")
    anchored = ReviewNote(id="n1", body="rename it", path="src/app.py", line=9, hunk="@@ -1 +1 @@")
    bare = ReviewNote(id="", body="overall: split this up")

    line = note_words(general)

    assert line == "[comment 660.1] Please make one_pass the default"
    found = COMMENT_LINE.match(line)
    assert found and found.group(1) == "660.1"
    answer = parse_answer(
        json.dumps({"replies": [{"comment_id": "660.1", "body": "done"}], "summary": ""})
    )
    assert answer and [r.comment_id for r in answer.replies] == [found.group(1)]
    assert note_words(anchored) == "[comment n1] src/app.py:9 — rename it\n@@ -1 +1 @@"
    assert note_words(bare) == "overall: split this up"
