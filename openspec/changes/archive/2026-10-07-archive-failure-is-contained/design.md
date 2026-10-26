# Design

## The loop

In `archive_ready_changes`, wrap `openspec.archive(change, …)` in a handler for the CLI's
error. On failure: log `archive of <change> failed — <first line of the message>` at warning
level and continue. Nothing is recorded: no state file, no fingerprint. The returned list holds
only changes archived. Ledger roll-up and run-log removal run only for archived
changes, as now.

## Retried on the next tick

A change whose archive failed is tried again on the next tick, with no memory of the failure.
Retrying is cheap (one CLI call that fails fast), so remembering a failure to skip it is not worth
a state file, and a failure that clears by itself (a lock, a network blip) clears at the next
tick. The warning line names the change and the reason, and repeats while the cause remains.

## Missing files

`is_ready_to_archive` is unchanged; before calling the CLI the archive step checks that the
change's directory exists. A missing one is logged at warning level as "withdrawn: no change
directory" and skipped, so the CLI is not called for it.

## `abk verify`

`cmd_verify` archives nothing itself; when its verification passes but the change is not archived
(the archive step failed or skipped it), it prints `<change>: verified but not archived (<reason>;
see the log)` and returns 1, so a person running it is told, rather than seeing silence and exit 0.

## Out of scope

Deciding what to do with a withdrawn change's units; archiving withdrawn changes by hand.
