## From `checkpoint-plain-values/1`

- The builder could not edit the change's files, so the deviation from task 1.2 is not recorded there. The values nodes return are checked from a run's writes in test_held_state_plain_text.py rather than by extending populated()/reachable(). A person may want to note that in the change's tasks or design.
- tests/checkpoint_types.py:56 — `node_updates(db, thread_id)` uses `thread_id` only to look up task names. Its `SELECT ... FROM writes` has no `WHERE thread_id = ?`, so it returns the writes of every thread in the file.
