# Tasks

Acceptance: none — housekeeping inside the tick; tier-1 tests over the archive step with a
failing runner prove it.

## 1. [agent-build-kit] [tier1] An archive failure is logged and skipped

Done when one change's failed or impossible archive no longer ends the tick, is logged and
tried again on the next tick, and `abk verify` says when a verified change was not archived.

- [x] 1.1 Test: with two finished changes and the runner failing for the first, the second
      is archived, the failure is logged with its reason, and the call returns normally.
- [x] 1.2 Test: a finished change with no directory is logged as withdrawn and the runner is
      not called for it.
- [x] 1.3 Test: a second call calls the runner for the failed change again, and logs the
      failure again.
- [x] 1.4 Test: `abk verify <change>` for a change that verified but was not archived prints
      the "verified but not archived" line with the reason and exits 1.
- [x] 1.5 Contain the failure in `archive_ready_changes` (logged at warning level, no record),
      add the directory check, and the "verified but not archived" line in `abk verify`.
- [x] 1.6 Describe it in `docs/architecture.md` and the `abk-pipeline` skill, and add a
      changelog entry.
