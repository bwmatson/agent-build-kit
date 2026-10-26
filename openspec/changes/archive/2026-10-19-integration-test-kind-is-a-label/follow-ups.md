## From `integration-test-kind-is-a-label/1`

- src/agent_build_kit/pipeline/unit_store.py:589 — `widest_kind([fresh.tier, existing.tier])` can keep a kind that no group still carries. If an unstarted unit's own group set the wider kind and is then retagged narrower, the unit keeps the old, wider label.
- src/agent_build_kit/cli/pipeline.py:2911 — When every group is taken, `_task_catalog(inst)` is now built twice in the same branch: once for `_tag_problems` and again at line 2919 for `_set_priorities`. Each build re-reads and validates every tasks.md.
