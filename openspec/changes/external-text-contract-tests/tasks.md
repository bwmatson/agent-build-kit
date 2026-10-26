# Tasks

Acceptance: none — adapters and recorded-message contract tests inside the pipeline;
tier-1 tests prove them.

## 1. [agent-build-kit] [unit-test] Git output in one adapter

Done when a push outcome and the replay notice are classified from porcelain output with
a fixed locale, a hook rejection is no longer reported as a stale lease, and recorded real
output pins it.

- [x] 1.1 Test: recorded real push output for a stale lease, a hook decline, a protected
      branch refusal, a non-fast-forward and an unrelated failure classifies each as
      `stale_lease`, `rejected_by_remote` (three of them) or `other`; only the first
      raises `StaleRemote`.
- [x] 1.2 Test: recorded rerere output yields the replayed files; an unrelated line does
      not.
- [x] 1.3 Test: the push runs with `--porcelain` and the fixed locale.
- [x] 1.4 Write `git_push_outcome` and the replay reader, route `push_with_lease` and
      the restack path through them, and add the fixtures with the git version noted.
- [x] 1.5 Document the adapters and the re-recording command in `docs/architecture.md`
      and the changelog.

## 2. [agent-build-kit] [unit-test] Agent CLI and ACP failures read structured fields first

Done when a rate limit, a lost session and a denied tool call are recognised from the
tools' structured fields before any phrase, and recorded events pin each.

- [x] 2.1 Test: recorded closing events for success, a rate limit (structured and text
      only), a session that is gone and a generic error classify as expected; success is
      an explicit subtype set.
- [x] 2.2 Test: recorded ACP updates for a denied call, an allowed one and an errored one
      classify by status and error fields, and the phrase list is used only when they
      are absent.
- [x] 2.3 Write `agent_failure` and `denied_call`, route the runtimes through them, take
      the protocol's stop-reason strings from the SDK's types, and add the fixtures.
- [x] 2.4 Update `docs/agent-runtimes.md` and the changelog.

## 3. [agent-build-kit] [unit-test] The red check reads pytest's report

Done when the red check decides from each failing test's exception type in a
machine-readable report and the console substring matching is only a logged fallback.

- [x] 3.1 Test: recorded reports for a missing implementation, an import error, a
      fixture error and a plain assertion yield accepted, rejected, rejected and the
      expected verdict for the last, each with its test names.
- [x] 3.2 Test: when the report cannot be written the fallback runs and logs that it
      did.
- [x] 3.3 Add the report option to the Python profile's red-check command, write
      `red_check`, route the stack runner's check through it, and add the fixtures.
- [x] 3.4 Update `docs/toolchain-profiles.md` and the changelog.
