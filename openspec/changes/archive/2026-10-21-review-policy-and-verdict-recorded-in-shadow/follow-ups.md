## From `review-policy-and-verdict-recorded-in-shadow/3`

- src/agent_build_kit/pipeline/units.py:126 — `review_tier` is typed `str | None`, so the model accepts any string, e.g. `review_tier="ful"`, and the store will write it and read it back.

## From `review-policy-and-verdict-recorded-in-shadow/2`

- config_guard.config_unchanged catches BaseException, so a KeyboardInterrupt or SystemExit raised while a config file differs comes out as ConfigChanged. That matches the spec's 'a run after which either file differs SHALL fail', but a docstring line saying so on purpose would stop the next reader from narrowing it to Exception.

## From `review-policy-and-verdict-recorded-in-shadow/6`

- tests/pipeline/test_verdict_never_lowers.py:66 — The comment above the history pick says "the thinner one stands for them", but the key now chooses the history with the lowest clean rate first and only breaks ties by fewest samples. For thin-history (1/1, rate 1.0) against low-clean-rate (20/10, rate 0.5), it picks the thicker one.
