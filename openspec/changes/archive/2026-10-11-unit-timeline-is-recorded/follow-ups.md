## From `unit-timeline-is-recorded/1`

- tests/cli/test_wait_reasons.py:284 — The new run_round test builds `cli._Readmission()` and fills its `started` map. That reaches a private name, and `run_round`'s public `started=` parameter already carries the same set.

## From `unit-timeline-is-recorded/2`

- In `abk report --waits`, the part of the review stretch after a person answered is filed under the `running_checks` cause, because the spec has no in-review checks cause. The state totals no longer depend on this, and docs/cli.md says so. A later unit could add an `in_review_checks_ms` cause so the cause columns line up with the state a unit was in.
- The `_review_entry` docstring (usage_report.py:1184) still says the review time is split 'as a person's, the rounds' and the checks''. The rounds now sit beside the review stretch, not inside it, so the docstring should say that, as `_ReviewSplit` already does.
