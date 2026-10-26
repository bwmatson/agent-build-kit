# Proposal

## Why

The pipeline keeps one state label on each pull request and replaces it when the unit's state changes. For the states it leaves unlabelled
(`merged`, `closed`, `unplanned`, `satisfied`) it does nothing at all, so the label the pull request had when it was open stays on it for good:
usually `in-review`, and occasionally `checking`, `planned` or `running`. A count over every non-open pull request found 109 `in-review`, 2
`checking`, 1 `planned` and 1 `running` in the code repository, 5 `in-review` in the platform repository and 1 in a third. Nothing reads a label
back, so it went unnoticed; but a merged pull request that says `in-review` is wrong on the one page a person looks at, and it breaks the rule that
exactly one state label, naming the unit's state, is on a pull request.

## What Changes

- **A finished unit's state label comes off:** when a unit's stored state becomes `merged`, `closed`, `satisfied` or `unplanned` and it has a pull
  request, every state label is removed from it. Change labels and labels a person added stay.
- **A way to see what is on a pull request:** the forge protocol gains `labels_on`, so the removal reads once and removes only what is there.
- **Existing stale pull requests heal themselves:** each tick clears the state labels of a bounded number of finished units' pull requests that have
  not been cleared yet and records them in a machine-local file. No command and no new field in the unit store.
- **Best effort:** a failure is logged once and never fails or delays a unit or a tick.

## Impact

- agent-build-kit: the state-label module, the forge protocol and its GitHub, Azure DevOps and local forges, the forge operations table, the
  round of a tick, the `limits` settings, the architecture, code-forges and configuration documents, and the changelog.
