## From `usage-read-on-decision/1`

- Type `decide_start`'s `decide` to show it is called with `trust_age=True` on the held-reading path (a Protocol), instead of `Callable[..., Decision]`.
- Move the tests that inject `usage=`/`decide=` into `build_may_start`/`build_resume_at`/`build_usage_gate` onto `tests/usage_host.Host` or `start=`, then remove the legacy path in `wiring._guard_decision` so every gate decides through `decide_start`.
- Reword the `Decision.resets_at` comment: it is filled for refusals as well as allowances.
- src/agent_build_kit/pipeline/usage_guard.py:936 — `decide_start`'s `decide` is typed `Callable[..., Decision]`. That hides the fact that the held-reading path calls it as `decide(held, trust_age=True)`.
- src/agent_build_kit/pipeline/usage_guard.py:189 — The comment on `Decision.resets_at` says it is the reset 'of the reading behind an allowance'. `carrying()` sets it on refusals too.
- src/agent_build_kit/pipeline/wiring.py:1356 — `_guard_decision` takes three overlapping injection points (`usage`, `decide`, `start`) and keeps two code paths only so existing tests can inject `usage=`/`decide=`.
