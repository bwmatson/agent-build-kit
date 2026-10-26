# Proposal

## Why

A unit's run leaves four traces, and the one that explains its behaviour is the least durable:

- **The journal.** Every line the tick prints — each step, each tool call, each agent's account of
  itself, the outcome — goes to `journalctl` and nowhere else. The service is configured
  `StandardOutput=journal`, and the framework writes no log file of its own.
- **The unit's record.** `runs/units.json` keeps its state history with notes, permanently.
- **The tracks' reports.** The scheduled tracks write dated Markdown into `runs/` and those are
  versioned.
- **`.last-runs/`.** The tracks' raw agent output, overwritten each run.

So the durable records say *what* happened and the transcript that says *why* is in a system
journal, keyed by time rather than by unit. Every failure diagnosed this week — a run that produced
no commits because its work was already done, a reviewer's actual objection, an adapt step short one
decision — was reconstructed by guessing a time window and grepping. After journald rotates, those
reconstructions are impossible.

There is precedent for the fix in the same directory: `runs/` already holds dated per-run reports
for the scheduled tracks, and `.gitignore` already excludes `runs/tick-*.log`, so the pattern and
its ignore rule both exist.

## What Changes

- **Each unit's run is written to its own file**, carrying the lines that tick prints for that unit
  and nothing else: the step, the model, each tool call, the agent's own summaries, and how the run
  ended.
- **The name begins with the unit**, then the run's start time, then the step — so a listing groups
  every run of one unit together and reads in order, which is how someone looks for them.
- **A unit's record names its most recent log**, so reading a failed unit leads to the transcript
  rather than to a time window to guess at.
- **They are machine-local and not versioned**, like the tick logs beside them, and they are pruned:
  a bounded number of runs per unit, and a unit's logs go when its change is archived.
- **The journal keeps getting everything.** This adds a copy organised by unit; it removes nothing.

## Impact

- **agent-build-kit**: where a unit's log lines are emitted, plus a pointer on the unit and an ignore
  rule.
- Diagnosing a failed unit becomes opening a file named after it.
- Some disk: a long run is tens of kilobytes, and pruning bounds the rest.
