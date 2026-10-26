## From `low-risk-units-land-without-a-person/3`

- src/agent_build_kit/forges/base.py:450 — The comment on `merges` says it is 'false unless a forge says so', but the Protocol attribute has no default. Every forge has to declare it, and a forge that does not fails the type check (or raises AttributeError) rather than reading as false.
- src/agent_build_kit/forges/base.py:453 — The new Protocol methods `merge_pr` and `merge_commit` have the body `raise NotImplementedError`. Every other Protocol method in this file ends with `...`.
- src/agent_build_kit/forges/__init__.py:19 — `MergeRefused` is not re-exported from `agent_build_kit.forges`, while its sibling `StackRefused` is. The stand-in imports it from `forges.base`.

## From `low-risk-units-land-without-a-person/4`

- tests/hooks/test_policy_merge_denial_unchanged.py:123 — The source-search test allows any path whose name merely contains "landing", and it only matches the literal `.merge_pr(` call form.

## From `low-risk-units-land-without-a-person/5`

- src/agent_build_kit/forges/azure_devops.py:885 — Every answer to the completion call other than `completed` with a merge commit is treated as a refusal. That includes an answer of `active` with `mergeStatus: queued` and no failure message, which is what an asynchronous completion looks like. The REST fake only covers the synchronous case: its PATCH copies the request body into the pull request and echoes it back as `completed`.
- src/agent_build_kit/forges/azure_models.py:43 — `MergeDoc` repeats `status`, `merge_status` and `last_merge_commit` from `PullRequestDoc`, which this change also extends. The PATCH reply is the same pull request document that `_pull_doc` parses.
- tests/forges/test_azure_merge.py:101 — `assert len(host.calls("PATCH", PULL)) <= 1` would also pass if the completion were never sent.
- tests/forges/test_azure_merge_parity.py:1 — Task 5.2 names `tests/forges/test_azure_rest_parity.py` for the parity tests, but they are in a new file, `test_azure_merge_parity.py`.

## From `low-risk-units-land-without-a-person/7`

- src/agent_build_kit/pipeline/events.py:309 — `clear_intent` runs after `_record_merge` inside the `try`, and an OSError from it (the lock's mkdir/open, or the write) propagates out of `on_merged` after the merge is already recorded.
- src/agent_build_kit/pipeline/events.py:2226 — `build_dispatch` still defaults `landing_path` to None, so a future caller can leave the intent read off without anything noticing.
## From `low-risk-units-land-without-a-person/8`

- src/agent_build_kit/pipeline/landing.py:102 — The rework also changed which declines get recorded. Only a unit with a final `auto` verdict now gets the 'not landed' log line and the `landing_declined` event. No round-1 finding asked for this, and no test covers it.
- tests/pipeline/test_landing_execution.py:158 — The child test calls `make_landable` again for `c/1`, which `Landing.__init__` already set up. The forge then lists pull request 1 twice.

## From `low-risk-units-land-without-a-person/13`

- src/agent_build_kit/pipeline/review_rates.py:107 — `audits` is optional (default None) on `recorded_gates`, `class_gates`, `class_rates`, `recorded_history` and `ClassHistory.from_records`. A new caller that leaves it out gets rates where an audited auto-landed unit never counts, and nothing warns them.

## From `low-risk-units-land-without-a-person/15`

- src/agent_build_kit/notify/cards.py:161 — The rework changed `record.get("lifted")` to `record["lifted"]` in `_demotion_cards`, so a dict record with no `lifted` key now raises KeyError. `standing_demotions` treats the same record as standing, so it passes that function's validation first.
- src/agent_build_kit/pipeline/landing.py:82 — The decline reason repeats the file name: `UnreadableDemotions` from `read_demotions` already begins with 'demotions.json cannot be read:'. The prefix added here makes the unit's note and log line read 'demotions.json cannot be read: demotions.json cannot be read: Expecting value ...'.

## From `low-risk-units-land-without-a-person/17`

- `_agreement` in demotion_triggers.py now decides whether a demotion stands by reading the raw record (`held.get("lifted") is None`). It no longer goes through `demotion_record.demoted_classes`, so the standing rule now lives in two places, and a malformed standing record no longer raises `UnreadableDemotions` on this path. A named accessor in demotion_record that returns a class's record and says whether it stands would keep that rule in one module.
