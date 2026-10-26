## From `a-runtimes-provider-has-usage-windows/1`

- In tests/config/test_config_gate_limits.py, the new test `test_a_gate_setting_under_limits_is_sent_to_the_gate` checks that the message contains `key` and `gate`. Both are always there, because every message starts with `gate.provider.limits.<key>`. Only the `claude_code not in message` check actually tells the two branches apart. Checking for the advice itself ("on `gate`, beside `provider`") would pin the wording.

## From `a-runtimes-provider-has-usage-windows/3`

- The `provider_decision` docstring in pipeline/usage_guard.py still says a standing hold lifts 'only when the usage plus the resume buffer is at or below the threshold'. Since round 2 the lift is decided by `relief_at`, which inverts the ramp exactly and can differ from that rounded-threshold wording by up to half a point. The docstring should say the hold lifts when `relief_at` offers room by `now`.
- `gate_result` no longer holds the lock while it fetches. Two evaluations of the same split that both miss the cache will each call the provider or command, and the last write wins. This is harmless for correctness, but the docstring line 'the file is written whole under a lock' could add that the fetch itself happens outside the lock, so the next reader knows a duplicate fetch is expected.

## From `a-runtimes-provider-has-usage-windows/4`

- In usage_guard.gate_result, the `persist=False` early return comes after `kind` is computed, and `kind` is used only on the persisting path. Moving the early return above it would make the dry-run path easier to read. A dry run still creates `gate-usage.json.lock` through file_lock. That is harmless, but it is a file a dry run writes.

## From `a-runtimes-provider-has-usage-windows/5`

- tests/cli/test_doctor_gate.py:258 — `imports_during` only patches `builtins.__import__`, and `importlib.import_module` does not go through that hook. Nothing checks afterwards that `acp` is still out of `sys.modules` or that `sys.modules['modal']` is still None.
- src/agent_build_kit/pipeline/usage_guard.py:1620 — Without `--refresh`, a provider reading whose window has already ended is now judged against the current time and shown with no word that its window is over.
