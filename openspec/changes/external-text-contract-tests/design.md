# Design

## Adapters

Each lives in one module and exposes a typed result: `git_push_outcome(result) ->
PushResult(kind)`, `agent_failure(event, text) -> AgentFailure(kind)` for the Claude
runtime, `denied_call(update) -> bool` for ACP, `red_check(report) -> RedResult`. Callers
use the typed result and never read the text again.

## Git

Push with `--porcelain` and `LC_ALL=C` (the untranslated environment helper already used
for rebase). The porcelain status line gives `!` with a reason in brackets; the stale
lease is `[rejected] (stale info)`, a hook or protection decline is `[remote rejected]`.
Kinds: `stale_lease`, `rejected_by_remote`, `other`. Only `stale_lease` raises
`StaleRemote`; the others raise a different error carrying the remote's message, so a
hook failure is not reported as a concurrent push. The rerere "Resolved … using previous
resolution" notice stays a pattern, with a test over real output.

## The agent CLI

Order: the closing event's `is_error` and status, then its subtype set, then the markers
(`usage limit reached`, `429`, the epoch form) over the CLI's own words only. Success is
`subtype in {success}` named explicitly. "No conversation found" stays a marker for the
session-unavailable case, with a recorded fixture.

## ACP

A tool call's denial is read from the update's status and raw-output error fields; the
phrase list is a last resort and says so. Protocol strings (`end_turn`, `cancelled`)
come from the SDK's literal types.

## The red check

Run the unit's new tests with a machine-readable report (the framework's pytest profile
adds it; the fixture file is a temp path) and read each failing test's exception type and
message from it: a missing-implementation error type is the accepted failure, an import or
fixture error is rejected. The console-substring matching stays only as a fallback for a
repository whose pytest cannot write the report, and logs that it was used.

## Contract tests

Fixtures under `tests/fixtures/external/` hold recorded real output with the tool and
version in the file header: push rejections of each kind, rerere output, CLI closing
events (success, rate limit, session gone, error), ACP updates (denied, allowed, errored),
and pytest reports (missing implementation, import error, fixture error, assertion).
Re-recording is a documented command; a test fails when a fixture's tool version is
older than the installed one's major version so drift is looked at.

## Out of scope

Forge host error text; file and configuration parsing; git plumbing formats.
