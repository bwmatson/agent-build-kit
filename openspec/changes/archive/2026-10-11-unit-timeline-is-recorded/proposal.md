# Proposal

## Why

An analysis of 72 merged units found the build agents are not the bottleneck: agent calls total 11.6 h
while units spent 1,343 h in `planned`, 172 h in `in_review` and 93 h in `running`. In 47 of 87 hours the
pipeline ran nothing, 17 of them with a full queue and 30 with room to spare. Most of that could only be
reached by a one-off script over tick logs, because the records do not say why a unit was waiting:
about 57 of the 93 `running` hours, the idle hours and the review waits cannot be attributed, a unit's
`ready` moment is not stored at all, the summary's `pause_wait_ms` and `review_wait_ms` are null on the
summaries that exist, and the per-tick logs that were the only evidence are not kept.

## What Changes

- **A defined set of wait reasons** (`WaitReason`, a `StrEnum`). Each pass computes one reason per unit
  that is not running; a decision log records it **only when the reason or what it waits on changes**.
- **Two new timestamps on the unit record**: when it first became ready, and when a person first
  answered its pull request. Start and entry into review are already in the unit's state history and are
  read from there.
- **Waits as spans** on the existing `waited` field, with the new reasons; a usage-paused unit displays
  as `paused`; review rounds are spans with a cause (review, check, conflict).
- **A sample row per refresh** of the running pass, so idle slots and concurrency over time are data.
- **The summary's wait fields are filled** for every unit.
- **`abk report --waits`** shows wall time by cause, idle-with-room hours and the estimate ratio per
  kind, and reproduces the analysis from the records alone.
- **The ledger is complete and the logs bounded**: every agent call on every path writes exactly one
  ledger row, the decision log and unit logs have retention.

Not included: any change to how units are ordered or started; this change only records.
