# Proposal

## Why

The risk-tiered review work renames the two kinds of test, so that "tier" can mean how much review a change gets. A rename that large
touches most of the tree, and work already planned will be built while it happens. The least disruptive order is to put a small layer in
first that makes both spellings work wherever one is read from outside the code, and only then rename the code. Work that has not
started can then be told to wait for the layer and is built with the new names available; work that has started is not interrupted and
keeps working, since the old spellings still read.

## What Changes

- **A type for the test kind.** `TestTier`, with the values `unit-test` and `e2e-test`, replaces the strings the code compares today.
- **A table of old and new spellings in one module,** for the tags of a task group heading, the keys of an `abk.yaml`, the values in the
  state files, the state-file names and the metric names, with the text of the notice.
- **Both spellings are read at the three edges that exist outside the code:** a `tasks.md` heading, an `abk.yaml`, and a stored unit
  or plan. The old spelling gives the same meaning and a notice naming the new one, from `abk tags`, `abk check`, `abk config` and
  `abk doctor`. A file that holds both spellings of one setting is refused.
- **Nothing is written under an old spelling.** What abk stores it stores with the new value.

## Impact

No behaviour change and nothing is renamed. A `tasks.md` or an `abk.yaml` written with the old spellings keeps working and now says
so; one written with the new spellings works as soon as this lands.
