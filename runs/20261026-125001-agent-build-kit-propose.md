# Propose 20261026-125001 — agent-build-kit

Tracked-issues refresh: both sections were empty; nothing to move.

## Issue chosen

- Health candidate 1 (suite red on the base commit, 7 failures, reproduced here). One issue
  was bounded and unambiguous: `test_without_a_url_it_names_the_setting_and_fails` depends on
  the host not setting `ABK_GRAFANA_URL`.

## Change written

`agent-build-kit-track-20261026-125001`, one group: `[agent-build-kit] [unit-test]` the test
clears the host's Grafana URL (failing test first, then the `delenv`). `abk check` and
`abk tags` pass.

## Left out — needs a person

The other six failures are guards flagging planning content (`openspec/specs/`, archived and
open changes, `runs/units.json`): home paths (26 hits), PR-number anecdotes (2), dated
anecdotes (3), a removed-key mention, "a person merges every PR" wording, and old live-test
module names (39). Fixing them means choosing between scrubbing historical planning content
and exempting `openspec/`/`runs/` from the guards, which conflicts with AGENTS.md saying the
guard reads planning content on purpose. That is a design decision, so no group was written.
Note: until it is made, the suite stays red and
`install-timers-carries-the-machine-files-into-the-pipeline-worktree/1` stays blocked even
after this change merges. If this stops all builds, AGENTS.md's "pipeline unable to run"
exception may apply to a direct fix.

No candidates were skipped for belonging to another repo.
