# Tasks

Acceptance: none — the plugin is tested with pytest's own test runner on small generated test files; tier-1 tests prove each case.

## 1. [agent-build-kit] [tier1] Tier-2 tests run under their own time limit

Priority: 1

Done when a test with the tier-2 marker is not failed by the sixty-second limit and has its own, and every other test keeps the sixty seconds.

- [x] 1.1 Test: a test carrying the tier-2 marker that runs longer than the fast limit passes, in its call, its own setup and a module-scoped
      fixture's setup; one that passes the tier-2 limit fails with a message that names the tier-2 limit; a test without the marker still
      fails at the fast limit with the message it has now.
- [x] 1.2 Test: the tier-2 limit has a default, is set by its option, and zero turns it off without changing the fast limit; the fast
      limit's option and default are as before.
- [x] 1.3 Add the second option and the choice of limit by marker to the time-limit plugin, and name the kind of limit in the failure message.
- [x] 1.4 Document the two limits and their options with the test markers in `docs/agent-runtimes.md`, and add a changelog entry.
