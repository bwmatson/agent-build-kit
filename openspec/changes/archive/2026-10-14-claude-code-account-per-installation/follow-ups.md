## From `claude-code-account-per-installation/1`

- Until group 3 lands, an installation that sets the account runs every claude in `<dir>` while the usage guard still reads `~/.claude/.credentials.json` and `~/.claude.json`. The changelog bullet should not be read as covering the guard until that unit folds its work into the bullet.
- Task 2.4 names `claude_holders` among what must find only the account's sessions. `tests/serve/test_chat_account.py` drives the listing, the session GET and the turn, but nothing pins the holders lookup on its own.
- src/agent_build_kit/claude_account.py:56 — `_supplied` matches process names case-sensitively (`name in os.environ`), but the settings layer matches them case-insensitively (pydantic-settings' default `case_sensitive=False`, which `Settings.model_config` keeps). Name lookup in the `.env` is already folded with `.upper()`; the process lookup is not.
- src/agent_build_kit/claude_account.py:25 — `NAMES` is derived from the field's `AliasChoices`, but the `Source` enum and the `_PROCESS` and `_ENV_FILE` maps hardcode the same two names, and `VARIABLE = NAMES[0]` would raise `IndexError` at import if the derivation ever gave `()`.

## From `claude-code-account-per-installation/3`

- The guard's headroom estimate (`most_added` in pipeline/usage_calls.py, called from usage_guard.py around lines 1030 and 1132) still pairs readings across a change of account. The spec limits the restart to the allowance calibration, so this branch is right to leave it alone. Whether the fastest-climb estimate should also restart at an account change is a question for a follow-up on the spec.
