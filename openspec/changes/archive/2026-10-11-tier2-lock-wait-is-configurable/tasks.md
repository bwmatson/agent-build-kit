# Tasks

Acceptance: none — a setting read where a constant was; config validation and a held lock are faked in tier 1, and nothing a consumer sees changes except that a queued unit waits longer before failing.

Priority: 1

## 1. [agent-build-kit] [tier1] Make the tier 2 lock wait a setting

Done when a person can set how long a unit waits for the tier 2 lock, the default is ninety minutes, both places that wait use it, a bad value is refused at load, and the busy message names the setting.

- [x] 1.1 Test: with no `limits.tier2_lock_wait_seconds` in the config, the loaded value is 5400.
- [x] 1.2 Test: with the setting at a number, the tier 2 runner built for a unit and `verify_one` given no wait of its own both pass that number to the lock, and `verify_one` given a wait still uses its own.
- [x] 1.3 Test: a config with the setting at 0, at a negative number, and at a value that is not a whole number (`90.5`, a word) fails to load, and the message names `limits.tier2_lock_wait_seconds`.
- [x] 1.4 Test: with the lock held and a configured wait of two seconds on a replaced clock, the busy error says it waited 2s and names `limits.tier2_lock_wait_seconds`; one raised for a wait the caller chose names no setting.
- [x] 1.5 Test: `abk config --show` lists `tier2_lock_wait_seconds` under `limits` with its default and with a configured value.
- [x] 1.6 Add the field to `LimitsConfig`, remove `DEFAULT_LOCK_TIMEOUT_SECONDS`, give `stack_lock` a required `timeout` and an optional `setting` label for its message, and pass the configured value from the tier 2 runner's one construction site and from `verify_one`.
- [x] 1.7 Document the setting in `docs/configuration.md` and in `skills/abk-config/SKILL.md`'s `limits:` block, and add a changelog entry.
