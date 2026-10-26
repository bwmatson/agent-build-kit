# Proposal

## Why

Human review happens on a code host's pull request page. Looking at what a unit did, commenting on
a line and sending the unit back means leaving the pipeline's own tools, and the comment reaches
the agent as `path:line — body` with no code around it, so the agent has to find the line again.

## What Changes

- **A review tab in the web UI:** the diff of a unit's branch against its base, split or unified,
  with a file tree, syntax highlighting, collapse, line and range comments, threads that anchor to a
  commit and are marked outdated when the branch moves, a general summary, and Request changes and
  Approve. The reviewer's findings and follow-ups are shown beside it.
- **Feedback enters through the existing seam:** a comment or Request changes from the UI is a
  comment or a changes-requested decision as far as the poller is concerned, with the same
  rework, same seen-tracking, and same replies, for a repo on any forge.
- **The hunk travels with the comment:** the rework prompt gets the diff hunk beside each inline
  comment, for review notes from every source, so the agent sees the code the comment is about.

## Impact

- agent-build-kit: the diff and review API and tab, a review store in the state directory, the
  poller's comment source, the review note and rework prompt.
- Depends on `abk-web-ui` groups 1 and 2; showing uncommitted changes and asking the agent about a
  selection also depend on `abk-web-ui` group 8 and `ui-chat-editing` group 3. Merging stays on the host.
