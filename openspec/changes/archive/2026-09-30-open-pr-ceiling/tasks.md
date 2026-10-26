# Tasks

Acceptance: none — these are readiness rules inside the pipeline, with no surface a
consumer drives; what proves it is tier-1 tests over the readiness rules, the order
they return units in, and the two lines of output.

## 1. [agent-build-kit] [tier1] A ceiling on open pull requests, and existing work first

Done when no new unit starts while the queue is at the ceiling, everything that
drains the queue still runs, the pipeline says which of the two is happening, and
free slots go to units with an open pull request, then to units resuming a build,
then to new ones.

- [x] 1.1 Test: the ceiling defaults to 5 and must be at least 1; open pull requests
      in different repositories count against the one ceiling; a pull request open
      while its unit is being reworked counts.
- [x] 1.2 Test: at the ceiling a unit that is otherwise ready is not started and
      stays waiting — not failed, not held; when a pull request merges and the count
      falls, it becomes startable under the existing rules.
- [x] 1.3 Test: at the ceiling, a unit that finishes its review loop still pushes
      and opens its pull request, and a rework, a restack and a further review round
      all still run — so the count can exceed the ceiling while in-flight work
      lands.
- [x] 1.4 Test: a pass that starts nothing because of the ceiling logs the count and
      the ceiling rather than reporting nothing ready, and the status output says the
      same.
- [x] 1.5 Test: with one free slot, a ready unit with an open pull request starts
      ahead of a ready unit that has never run and was planned earlier; a ready
      unit resuming a paused build starts ahead of a new one; with two slots and
      one of each of the three, the new unit is the one left waiting.
- [x] 1.6 Test: units of one kind start in the order they were planned; and the
      ordering admits nothing the other rules refuse — a resuming unit with no
      pull request waits at the ceiling while a rework starts, and a unit with an
      open pull request that is waiting on a dependency is not started.
- [x] 1.7 Add the ceiling to the configuration with its validation, and the
      condition to the readiness rules beside the concurrency and depth caps.
- [x] 1.8 Order the units the readiness rules return: open pull request, then
      resuming, then new, keeping the planned order within each.
- [x] 1.9 Add the reason to the tick's log line and to `abk status`.
- [x] 1.10 Document it in `docs/configuration.md` and the `abk-config` skill, and
      correct `docs/architecture.md` where it says pull requests awaiting review are
      deliberately unbounded — noting that the count includes every open pull
      request, not only those awaiting review — and where it describes which unit
      starts next.
