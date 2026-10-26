## From `units-are-triaged-by-review-tier/5`

- Nobody has run vitest or `uv run poe web-check` on this branch: web/node_modules is not installed in the review or build checkouts. Before merging, run `uv run poe web-check` and confirm that web/src/review/tier.test.tsx and web/src/pages.test.tsx pass.
- The checks round raised the e2e-test limit in tests/replay/test_replay_proxy_lifetime.py from 1 to 5 seconds. That test belongs to another feature, and it still depends on a wall-clock limit. A later change could inject the limit or the wait so the test no longer depends on the clock.

## From `units-are-triaged-by-review-tier/9`

- test_a_verdict_recorded_for_another_unit_while_deriving_is_kept writes the other unit's record with a plain write_text from inside the forge stub. Writing it through verdict_record's own recording function (`record_verdict`) would also check that the sweep no longer holds `verdicts.json.lock` while it calls the forge. With the plain write, the test would still pass if the lock were held there.

## From `units-are-triaged-by-review-tier/11`

- This unit follows its spec ('a proven class → tier auto'), but design.md's 'Cards follow the tier' and 'An auto unit waits without a card' still say the history floor holds every class at light, so no unit can reach auto. Now that the floor reads real history, a class whose own record clears min_samples/min_clean_rate gives units tier auto, and those units get no review card (only `abk status` lists them as awaiting review), even though nothing lands them yet and no `review.auto_land.classes` allow-list exists. A person should either accept this and update the design text, or add a hold until the landing change: don't suppress the card unless the class is explicitly allowed.
- src/agent_build_kit/pipeline/verdict.py:156 — The rates are shared now, but the gate comparison is still written twice: once in `compute_verdict`'s history floor (`samples < min_samples`, `clean / samples < min_clean_rate`) and once in `review_rates.class_gates` (src/agent_build_kit/pipeline/review_rates.py:84-85: `more == 0 and (rates.clean_rate or 0) >= min_clean_rate`).
- src/agent_build_kit/pipeline/verdict.py:43 — `ClassHistory.from_records` needs a function-local import of `review_rates`, because review_rates imports `ReviewTier` from this module. That gives the pure facts-to-tier module a dependency on the verdict file's record shape.
