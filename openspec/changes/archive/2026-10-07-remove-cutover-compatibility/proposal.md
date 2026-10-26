# Proposal

## Why

The unit-graph cutover added code to move units in flight from the classic engine onto graph
threads: a conversion that runs on every tick, a `classic_run` field and a loader that folds
the old top-level fields into it, and a `resume_from` field nothing writes. None of it has
anything left to bridge: no live unit has the old fields set, and none is waiting for a
conversion. It still runs on every tick, shapes the unit store's schema, and is tested.

`status-not-wording` adds a smaller bridge, the log lines and documents that name units with no
recorded cause. They were wanted for the handful of units in flight at that cutover.

There are no releases to wait for: the version is 0.1.0, nothing is tagged, and every changelog
entry is Unreleased.

## What Changes

- **The cutover bridge is deleted:** the conversion module and its call on each tick, the
  `classic_run` field with its loader and carry, the `resume_from` field, the clearing helper
  the converter alone used, the documents that describe moving units in flight, and the tests
  that exist only for them.
- **An old-shaped store fails loudly:** a units store with any of the old top-level fields no
  longer loads quietly; the error names the field and says to finish or requeue the old work
  first. This is recorded in the changelog as breaking.
- **The no-recorded-cause bridge is deleted:** the tick-time log lines and the document
  paragraphs about units with no cause. A unit with no cause is simply not readmitted by a
  running pass, and `abk status` may keep listing such units as a permanent diagnostic.
- **What stays:** the tolerance for a cause written by a newer release; the usage ledger's
  tolerant reader; the rules-version mechanism of `abk init`; credential and telemetry
  environment aliases; the runtimes' and the red check's behavioural fallbacks.

## Not here

Renamed-setting shims: none remain; they were removed together and recorded as breaking.
