# Tasks

Acceptance: none — one classification inside the runner, with no surface a consumer
drives; tier-1 tests over an empty step against an exhausted window prove it.

## 1. [agent-build-kit] [tier1] An empty step against a spent window is a pause

Done when a step that writes nothing while usage is exhausted pauses its unit in the
existing shape, a running step is still never interrupted, and an empty step with usage
to spare is left to be judged elsewhere.

- [x] 1.1 Test: a step that writes nothing while the usage reading says the window is
      exhausted leaves the unit planned, with a note in the form the boundary gate
      writes and a record of continuing at that step; its outcome reads as paused.
- [x] 1.2 Test: the reading used is the one already held — no additional usage call is
      made when a step ends, and none at all while a step runs.
- [x] 1.3 Test: a step that writes nothing while the window is healthy does not take
      this path.
- [x] 1.4 Test: the unit graph draws such a unit as stopped for usage; the resume the
      pause scheduled may build it, and it continues at the step that did not finish
      with its earlier commits intact.
- [x] 1.5 Add the classification where a step's empty result is judged, taking the
      existing pause path rather than a new one.
- [x] 1.6 Say in `docs/architecture.md`, beside the usage guard, that steps are never
      interrupted and that an empty step against a spent window is a pause, and note the
      same in the `abk-pipeline` skill's states table.
