## From `a-test-only-group-commits-no-pair/1`

- `commits_of_test_only_groups` in `pipeline/commit_order.py` zips `_commits` (rev-list) with `branch_subjects` (log --format=%s) using strict=True, after the gate's old strict=False. On a branch whose oldest or newest commit has an empty subject (made with `--allow-empty-message`), `git_out`'s stripping drops that line, the two lists differ in length and the gate raises instead of reporting a problem. Reading sha and subject from one `git log --format='%H %s'` call would keep the two lists aligned by construction.

## From `a-test-only-group-commits-no-pair/4`

- src/agent_build_kit/graph/nodes.py:1448 — The settle_group docstring still says it stops 'when the branch holds no pair for it'. unpaired now also reports a missing tests commit for a test-only group.
