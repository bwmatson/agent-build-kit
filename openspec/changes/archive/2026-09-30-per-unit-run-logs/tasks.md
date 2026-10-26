# Tasks

Acceptance: none — a log file and a pointer, with no surface a consumer drives; tier-1 tests over a
run's emitted lines prove it.

## 1. [agent-build-kit] [tier1] A run log per unit, named for the unit

Done when each unit's run is written to a file whose name begins with the unit, a unit's record names
its most recent one, the files are ignored by version control and bounded, and the pipeline's own
output is unchanged.

- [x] 1.1 Test: a unit's run writes a file whose name begins with the change and the padded unit
      number, then the start time, then the step; two units of one change sort in numeric order, and
      two runs of one unit sort by time.
- [x] 1.2 Test: the file opens with the unit, change, step, model, base and start time, carries the
      lines emitted for that unit, and closes with the outcome; lines belonging to other units are
      not in it.
- [x] 1.3 Test: the unit's record names its most recent run file, and a failed unit's record does
      too.
- [x] 1.4 Test: only the bounded number of runs per unit is kept; archiving a change removes its
      units' logs; the pipeline's printed output is unchanged by any of this.
- [x] 1.5 Write the per-unit file where the pipeline emits a unit's lines, in a directory of its own
      under the state directory, and record its name on the unit.
- [x] 1.6 Prune to the bound when a log is written, and remove a change's logs where a change is
      archived.
- [x] 1.7 Ignore the directory in the planning repository's `.gitignore`, beside the per-tick logs,
      and say in `docs/architecture.md` where state on disk is described that a unit's run log lives
      there and what its name means.
