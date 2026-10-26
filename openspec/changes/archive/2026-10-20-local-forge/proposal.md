# Proposal

## Why

`ui-review` lets a reviewer comment in the pipeline's own UI, but the unit still has to have a pull
request on a code host: the pipeline opens one, polls it and learns of the merge from it. For a repo
with no remote, or where reviewing in the UI is wanted instead of the host, the pull request is
overhead and a dependency.

## What Changes

- **A `local` forge:** a repo may set its forge to `local`. Opening, finding, updating and closing a
  pull request, listing pull requests, and posting and reading review notes are kept in a file in the
  state directory; labels, drafts, statuses, checks and stacks do nothing.
- **A merge is seen from git:** a local pull request is merged when its branch tip is an ancestor of
  the trunk, or its change is already in the trunk by patch identity; the existing poller path then
  runs unchanged.
- **Merging stays with a person:** the UI records Approve and Request changes only. Nothing in the
  pipeline or the UI merges.
- **The pipeline works without a remote:** pushing, fetching and the base comparison use the
  repo's own trunk when there is no `origin`.
- **The agent can read its pull request:** `abk pr view` and `abk pr diff` are the read-only commands
  the forge declares for its agents.

## Impact

- agent-build-kit: a forge implementation and registration, local-aware push and base handling, a
  merge check, two read commands. Depends on `ui-review`.
