# Design

The node label of a unit in the graph page is built from its identifier, title, carried groups, tier, state and pull
request. The extra line for a unit over the ceiling is removed, and nothing replaces it. The recorded actual size, the log
line and the status listing are unchanged, so the metric is still read where progress is read: the status command lists each
unit over the ceiling with its estimate and its actual lines.

The requirement that records a unit's actual size is restated without the page. Its scenario for a unit that lands over the
ceiling says that the log and the status say so and that the page does not.

Three places say the page marks a unit and are corrected with the label: the test that asserts the mark is rewritten to assert
its absence, the comment on `max_unit_lines` in `config.py` and the sizing paragraph of `docs/architecture.md` lose the words
"marked on the graph page".
