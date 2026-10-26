## From `a-started-unit-keeps-its-groups/1`

- src/agent_build_kit/pipeline/unit_store.py:1137 — `_new_collisions` compares whole `Collision` values, and those include `owner_state`. A collision that is already in the store therefore counts as new whenever the merge changes the started owner's state.

## From `a-started-unit-keeps-its-groups/2`

- src/agent_build_kit/pipeline/unit_store.py:753 — `UnitStore.retire` calls `_record_state` directly and repeats `set_state`'s `on_state` call itself. It does not go through `set_state`, so it skips the one retry `set_state` makes when the store file reads as torn (lines 900-914).
