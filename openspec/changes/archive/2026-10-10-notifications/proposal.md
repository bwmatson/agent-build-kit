# Proposal

## Why

Reviews and failed units have waited about ten hours overnight with no one told. The pipeline has no way to
reach a person: it writes to a log and to pull requests, and it runs under WSL, where a desktop notification has
to come from a Windows process. A notification sent as an event ("this unit failed") also goes stale, because
nothing takes it back when the unit is requeued, fixed or merged, and a person is left with cards that are no
longer true.

## What Changes

- **Cards are reconciled, not sent.** After each tick's poll the pipeline computes the cards the units call for
  (one for a unit in review with no rework pending, one for a failed unit and for a held unit that needs a
  person), compares them with the set it showed before, shows the new ones and clears the ones no longer called
  for. A card therefore clears exactly when its reason ends.
- **Cards are shown once and reminded on a schedule:** never duplicated across ticks or passes, sounded again after
  `remind_after_minutes` (default 30), and held back for `delay_minutes` (default 10) so a failure that is fixed
  quickly never shows.
- **A provider interface** (`Notifier`: `show(id, title, body, link)` and `clear(id)`), with a `command` provider
  that runs a configured template, and a `windows` provider that raises a toast through BurntToast from
  WSL or Windows.
- **Setup and checking:** `abk init` detects WSL or Windows and offers to enable notifications and to install the
  module, showing the install command first and running it only on a yes; `abk doctor` checks the chosen
  provider's prerequisites.
- Off by default; a failing provider is logged and never fails a tick.

## Impact

- agent-build-kit only: a new `notify/` package, a `notifications` section of `abk.yaml`, a step in the pipeline
  round, the `abk init` prompt and an `abk doctor` check, with docs. Nothing crosses to another repo, and no
  contract is widened.
- The first round covers ready-for-review and failure cards only.
