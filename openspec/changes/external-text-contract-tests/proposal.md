# Proposal

## Why

Some decisions can only come from another program's output. Matching it is unavoidable,
but it is spread through the code and tested against wording the authors wrote
themselves. Where it is loose it misclassifies:

- A rejected `git push` is recognised by the words "stale info" or "rejected" in its
  output. "rejected" also appears when a hook declines the push or a protected branch
  refuses it, so those are reported as someone else having pushed first.
- A rate limit from the agent CLI is recognised by marker phrases in its text. A missed
  one retries all night. The CLI's closing event has structured fields that are checked
  after the text, not before.
- An agent's denied tool call is recognised by phrases in its tool output, and the
  ACP stop reasons by strings.
- The red check decides that a test fails for the right reason by looking for the word
  "assert " or "fixture" anywhere in pytest's output.

The forge hosts' error text is covered by the forge transport changes and is not here.

## What Changes

- **Git push outcomes come from `git push --porcelain` with a fixed locale,** classified
  into stale lease, rejected by a hook or protection, and other, by an adapter that is the
  only place the output is read. The rerere replay notice gets the same treatment.
- **The agent CLI's rate limit and session errors are read from structured fields first**
  (the closing event's error flag, status and subtype), then by markers, in one adapter;
  success is an explicit set of subtypes, not a prefix test.
- **The ACP adapter classifies a denied call from the protocol's own status and error
  fields before any phrase,** and its protocol strings are the SDK's types where it has
  them.
- **The red check reads pytest's structured result** (a machine-readable report: the
  failing tests and their exception types) instead of substrings of the console output.
- **Every adapter has a contract test over recorded real messages,** kept as fixtures
  with the tool's version noted, run with the ordinary suite.
