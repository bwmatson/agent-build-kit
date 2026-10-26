# Proposal

## Why

`archive_ready_changes` archives each change whose units have all finished and lets the
OpenSpec CLI's failure for any one of them raise out of the tick. A change that was
withdrawn while its unit was already planned had its files removed; its unit finished, the
change counted as ready to archive, and archiving it failed with "Change not found". The tick
raised and exited with an error, and so did every tick after it, once every five minutes for
about fourteen hours, with nothing built or reviewed.

Archiving is housekeeping. Whatever goes wrong with one change's archive must not stop the
pipeline from building the others.

## What Changes

- **A failed archive is contained.** When archiving a change fails, the tick logs the
  change and the CLI's message at warning level, and goes on to the next change and to
  scheduling. The tick still exits successfully. The failure is not recorded anywhere: the
  archive is tried again on the next tick, which is cheap, and the log line is the signal.
- **A change whose files are gone is recognised.** A change that is ready to archive but has
  no directory is logged as withdrawn and skipped, not attempted.
- **`abk verify` says so.** When a verification passes but the change is not archived,
  `abk verify <change>` prints a "verified but not archived" line and exits 1, instead of
  exiting 0 without a word.
- **Verification failures were already contained;** this makes archive the same.
