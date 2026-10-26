# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/`.

- `pipeline/tier2.py` has `DEFAULT_LOCK_TIMEOUT_SECONDS = 3600` and `stack_lock(path, timeout=DEFAULT_LOCK_TIMEOUT_SECONDS)`, which raises
  `TimeoutError(f"tier 2 is busy: waited {timeout:.0f}s for {path}")` once the deadline passes.
- The tier 2 runner, `Tier2Session` in `pipeline/wiring.py`, takes `timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS` and passes it to `stack_lock` in both
  of its paths. It is built in one place (`Tier2Session(...)` in the unit thread's setup in `wiring.py`), which does not pass a timeout, so the default
  always applies.
- `verify_one` in `cli/pipeline.py` passes `timeout=wait` only when given a `wait`; otherwise `stack_lock`'s default applies. `cmd_verify` passes none;
  the round passes `wait=0` (it verifies only when the lock is free). It maps `TimeoutError` to `StackBusy`.
- Limits live in `LimitsConfig` in `config.py`: `tier1_command_seconds: Annotated[float, Field(gt=0)] = 3600` is the pattern, a documented field with
  a comment, a pydantic constraint and a default. They appear in `docs/configuration.md` and the `abk-config` skill, which ships inside the
  framework (`skills/abk-config/SKILL.md`) and repeats the `limits:` block. `abk config --show` prints `config.model_dump(...)`, so a new field
  appears without code in `config_cmd.py`.
- `tier2-tests-have-their-own-time-limit` (archived) limits a single test; it has no bearing on the wait for the lock.

UNVERIFIED: how pydantic's message for a refused field reads once `config.load` wraps it, and whether it names `limits.tier2_lock_wait_seconds` or only
the field. The builder checks and, if the key is not in the message, adds it in the validator's own text.

UNVERIFIED: whether the tier 2 runner is built anywhere other than the one place named above (a test double, a second path). The builder greps for
`Tier2Session(` and `stack_lock(` and passes the setting at each production call.

## The setting

`limits.tier2_lock_wait_seconds: Annotated[int, Field(gt=0)] = 5400`.

- **Name and place.** Under `limits`, with the `_seconds` suffix the other time limits use (`tier1_command_seconds`, `tier1_abort_grace_seconds`).
- **Integer, positive.** A whole number of seconds; a wait has no use for fractions. Pydantic's integer rule accepts `5400.0` and refuses `90.5`,
  which is accepted behaviour here. Zero is refused rather than meaning "do not wait" or "wait forever": two readings of one number is how a
  person gets the other from the one they meant, and a caller that wants no wait (`verify_one(wait=0)`) already says so with its own argument.
- **Default 5400.** Ninety minutes is above the longest run seen (61 minutes) with room for one run to queue behind another. It is a default, not a
  promise: a person with longer runs raises it.
- **Failing at load** is `LimitsConfig`'s ordinary field validation, so a bad value stops `abk` before any unit starts rather than failing a unit
  hours in.

## Where it is read

- `Tier2Session` takes its `timeout` from the installation's limits at the one place it is built, and `verify_one` uses the same value when it is not
  given a `wait`. A given `wait` (the round's `wait=0`) still wins, as now: it is the caller's own choice, not the setting.
- `DEFAULT_LOCK_TIMEOUT_SECONDS` is removed. `stack_lock`'s `timeout` has no default, so a caller that forgets to pass one is a type error and not a
  silent hour. Callers inside the framework's own tests pass a number.

## The message

`tier 2 is busy: waited 5400s for <path>` gains the setting: `tier 2 is busy: waited 5400s for <path> (limits.tier2_lock_wait_seconds)`. The setting is named
when the value came from it. A wait the caller chose (`wait=0`) names no setting, since changing the setting would not change that outcome. `stack_lock`
takes an optional `setting` label for the message; the two callers that pass the configured value pass the key.

## Relation to `tier2-lock-wait-holds-the-unit`

That change, still unbuilt, removes the deadline entirely and says "no configurable ceiling". This change is the interim fix: it makes the deadline a
setting now, with a longer default, because units are failing today and that change is larger.

When `tier2-lock-wait-holds-the-unit` is built after this one, it supersedes the deadline as the default behaviour: a unit then waits without limit.
**Recommended for what happens to the setting: it stays as an optional ceiling.** Set to a number, a unit's wait ends in the busy failure at that many
seconds, as now; the holds change's default becomes "no deadline" (the setting accepts null for that). The alternative is to remove the setting when
the deadline goes. Keeping it costs one nullable field and gives a person with a wedged-holder worry a way to bound the wait; removing it matches the
holds change's "no ceiling" reasoning exactly but turns a configured value into an error for anyone who set it. **To confirm with the person.** If
confirmed, that change adds the null case and its default (and `tasks.md` of that change gets a group saying so); this change does not decide it.
To keep this change self-contained the holds change's tasks gain a `Needs:` line on this one, so the setting exists before that change builds on it.

## Tests, and no tier 2

Config validation, a held file handle and a clock; no live stack. The group is `tier1` and `tasks.md` opts out of acceptance with a reason.

## Not included

Removing the deadline, showing the wait, recording the holder (`tier2-lock-wait-holds-the-unit`), and a separate setting for post-merge
verification's wait.
