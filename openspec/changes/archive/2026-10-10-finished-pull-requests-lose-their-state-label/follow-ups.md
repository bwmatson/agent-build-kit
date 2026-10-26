## From `finished-pull-requests-lose-their-state-label/1`

- Make the NoLabelsForge fakes in tests/pipeline/test_labels.py and tests/pipeline/test_state_labels.py raise NotImplementedError from `labels_on` too, so they match the four-method no-labels contract in docs/code-forges.md.
- Parametrize test_a_failed_clear_leaves_the_unit_finished over a failed read and a failed removal separately. At the store level it currently only reaches the read failure.
- tests/pipeline/test_state_labels.py:115 — The `NoLabelsForge` fakes here and in tests/pipeline/test_labels.py:78 override add/set_exclusive/remove_label to raise NotImplementedError but not the new `labels_on`. They inherit StandInForge's working read, so they no longer stand for 'a host without labels raises from all four label methods' (docs/code-forges.md).
- tests/pipeline/test_state_labels.py:521 — test_a_failed_clear_leaves_the_unit_finished sets both 'read' and 'remove' errors. The read fails first, so through the store it only checks that a failed read leaves the unit merged; a failed removal through the store is never exercised.

## From `finished-pull-requests-lose-their-state-label/2`

- test_the_record_is_written_under_its_lock relies on a 0.5s Timer firing after the round has written its record when the write is unlocked; on a heavily loaded worker the round could in principle take longer than that and the test would then pass without proving the lock. Widening the window or signalling from the write path would make it deterministic.
