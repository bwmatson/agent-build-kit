## From `acp-tests-follow-the-graph-log/1`

- docs/unit-graph.md testing section: say that the `<unit>: <node>: …` shape belongs to the tick log, and that the run log's lines are `[<time>] <node>: …` with no unit id.
- docs/unit-graph.md:534 — The new sentence says the run log's lines are `<unit>: <node>: …`, but the unit's run log doesn't have the unit id. `say` in `cli/pipeline.py` writes `[<time>] <node>: …` to the run log. Only the tick log (journal) has the `<unit>: ` prefix, and that is the stream `test_progress_is_visible_while_the_run_works` reads.
