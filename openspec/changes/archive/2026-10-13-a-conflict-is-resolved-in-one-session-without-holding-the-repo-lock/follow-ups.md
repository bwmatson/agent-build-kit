## From `a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock/1`

- tests/restack_turn_fakes.py:233 — `Rig.temporary_tree` writes out the branch-to-directory rule again (`restack-{branch.replace('/', '_')}`), the copy that [1.4] removed from the source.
- tests/graph/test_restack_branch_moved.py:32 — `asked.append(kw.get('resolve', True))` records a value that is never `resolve`. The test only uses the list's length.
