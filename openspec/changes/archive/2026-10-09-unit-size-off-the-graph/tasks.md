# Tasks

Acceptance: none — one label on one page; a tier-1 test proves it.

## 1. [agent-build-kit] [tier1] The graph page shows no size mark

Done when a node over the ceiling reads as one under it, and the log and status are unchanged.

- [x] 1.1 Test (replacing `test_the_graph_page_marks_a_unit_that_landed_over_the_ceiling` in `tests/pipeline/test_over_ceiling_view.py`,
      which asserts the old marking, while its status test stays): the graph page for a unit whose actual size is over the ceiling has a node label identical to the one
      for the same unit under the ceiling, and contains neither the landed lines nor the words "over the ceiling".
- [x] 1.2 Test: the unit still records its actual size, the log still says it is over the ceiling, and the status command
      still lists it with its estimate and actual lines.
- [x] 1.3 Remove the size line from the node label.
- [x] 1.4 Update `docs/architecture.md` (the sizing paragraph, which says an over-ceiling unit is "marked on the graph page") and the comment on
      `max_unit_lines` in `config.py`, which says the same, and add a changelog entry.
