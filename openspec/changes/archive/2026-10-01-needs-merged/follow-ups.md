## From `needs-merged/1`

- tests/pipeline/test_unit_store.py: test_a_stored_unit_without_merge_before_loads_unchanged branches on `isinstance(raw['units'], dict)`. That hedges on the store's on-disk shape. Pin the one shape UnitStore actually writes, so the test fails loudly if that shape changes rather than adapting to it silently.
- waiting_on's docstring (units.py) runs the merge_before rule into the cross-repo sentence ('— as does a same-repo one the unit lists in merge_before — except a satisfied cross-repo dependency...'). The code now judges a gated dependency as itself, before any satisfied look-through. Give that its own sentence so the next reader doesn't assume a gated dependency is expanded like the others.
