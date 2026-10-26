# Design

## The name is the interface

These files are read by a person looking for one unit's history, so the name answers that first:

```
<change>-<nn>-<YYYYMMDD-HHMMSS>-<step>.log
```

- **the unit first**, so `ls` groups every run of one unit together, which is the request and the
  right default: the question is almost always "what happened to this unit", not "what ran at 22:44";
- **its number zero-padded**, so unit 2 and unit 10 of one change sort in order rather than
  lexically;
- **then the start time**, so successive runs of the same unit read top to bottom;
- **then the step** — implement, review, rework, adapt — because a unit's failures usually belong to
  one step and naming it saves opening the file.

The tracks name their reports the other way round, time first, and that is right for them: a track
report is about a moment, and a unit log is about a unit.

## Where they live

A directory of their own under the state directory, rather than loose beside the tick logs and the
tracks' reports. `runs/` already holds eighty-nine versioned files and a handful of ignored caches;
adding a file per unit run to it makes listing the directory useless for either purpose.

They are ignored, like `runs/tick-*.log`. The comment in `.gitignore` already draws the line these
fall on: `runs/units.json` is versioned because it is the record of planned work, and everything
that changes on every tick and means nothing on another machine is not.

## What goes in one

The tick already prefixes each line with the unit it belongs to, so the content is that unit's slice
of the pass — not a new format, the same lines. Worth adding at the top, once: the unit, its change,
the step, the model, the base it is building on, and when it started; and at the bottom, how the run
ended. A file that opens with "which unit, which step, which model" answers most questions before
the transcript is read.

## Finding it from the record

A log nobody can find is a log nobody reads, and the entry point when something goes wrong is the
unit's record — that is where a person and an agent both start. So the unit carries the name of its
most recent log, and a failure's note can point at it. That closes the loop the journal cannot: from
"this unit failed and here is why in one line" to the run that produced it.

## Pruning

Two bounds, because an unbounded log directory is a slow leak:

- **per unit**, keep the most recent few runs — a unit that has been reworked five times is
  interesting for its last two, and the rest is history the change's own record already summarises;
- **per change**, drop its units' logs when the change is archived, since the change is finished and
  its specs have been folded into the repository.

Neither needs a scheduler: both are cheap checks at the moment a log is written or a change is
archived.

## What this is not

Not a replacement for the journal, which stays exactly as it is and keeps the whole pass in one
place including the lines that belong to no unit. Not a structured event stream — there is a case for
one, but the value here is that a person can open a file and read what an agent did, and that is
served by the text the tick already prints.
