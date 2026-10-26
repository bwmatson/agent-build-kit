## From `review-method-and-evidence/1`

- src/agent_build_kit/pipeline/stack_runner.py: `_unresolved` and `_render_open` both call `_open_entries` on the same inputs in the same loop iteration. The loop could call `_open_entries` once and derive both the ids and the rendered text from that one result.
- tests/pipeline/test_review_findings.py `test_an_unreadable_finding_blocks_approval` only checks what `parse_verdict` returns: a required `(unreadable)` finding. It never runs the loop to show that approval is actually refused. Either rename it (for example `test_an_unreadable_finding_parses_as_required`) or drive it through `_run` and assert that a rework round follows.
