## From `a-replaced-unit-points-to-its-successor/3`

- tests/cli/test_link_needs_repoints_replaced.py:124 — The name `test_an_edge_with_no_successor_is_left_alone_beside_one_that_is_repointed` no longer matches what the test checks. In the port, its assertion changed from ('x/3', 'y/5') to ('y/5',). That change is justified: the predecessor's `_drop_stale_edges` now removes a dependency on a parent that builds nothing, has no successor and is named by no `Needs:` line. But the edge is no longer left alone.
- docs/unit-graph.md:960 — The sentences reworded for 1.3 ('in any unit that has not finished, started or not') were not rewrapped. Here and at docs/architecture.md:141 the lines now run past the paragraph's wrap width.
