# Proposal

## Why

Tier 2 is serialized behind one lock file in the state directory. A unit whose tier 2 tests are ready waits for the lock for a fixed 3600 seconds
(`DEFAULT_LOCK_TIMEOUT_SECONDS` in `pipeline/tier2.py`) and then fails with `tier 2 is busy`, although nothing is wrong with it and its tests never
ran. One tier 2 run now takes 40 to 61 minutes or more, so any unit queued behind a full run fails. No setting exists for the wait, so a person cannot
change it without editing the framework.

This is urgent and small: a setting with a longer default, now. The bigger change, `tier2-lock-wait-holds-the-unit`, removes the deadline and makes
the wait visible; it is a larger piece of work and is built after this one (design: "Relation to `tier2-lock-wait-holds-the-unit`").

## What Changes

- **A new limit, `limits.tier2_lock_wait_seconds`**, the longest a unit waits for the tier 2 lock before its tier 2 step fails as busy. Default
  **5400** seconds (ninety minutes), a positive whole number.
- **It is checked at config load.** Zero, a negative number and a value that is not a whole number are refused, and the message names the key.
- **Every place that applies the wait reads it:** the tier 2 runner and `verify_one` (post-merge verification when it is given no wait of its own). The
  hard-coded constant is removed.
- **The busy message names the value and the setting** that produced it.
- **`abk config --show` lists it**, and the config reference, the `abk-config` skill source and the changelog describe it.

## Impact

- agent-build-kit: `config.py` (`LimitsConfig`), `pipeline/tier2.py` (the removed constant), the tier 2 runner in `pipeline/wiring.py`, `verify_one`
  in `cli/pipeline.py`, `docs/configuration.md`, `src/agent_build_kit/skills/abk-config/SKILL.md`, `CHANGELOG.md`.
- Spec: `test-tiers`.
