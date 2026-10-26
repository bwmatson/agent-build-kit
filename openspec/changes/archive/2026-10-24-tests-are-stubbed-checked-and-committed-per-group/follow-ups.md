## From `tests-are-stubbed-checked-and-committed-per-group/11`

- The new architecture.md test only checks that three names appear in the document (stub_checks, fix_stub_checks, per_group_commits). A drift in the description of resume, or of the stop when a group has no pair, would still pass. A later unit could make it check those sentences too, as the unit-graph test does.

## From `tests-are-stubbed-checked-and-committed-per-group/12`

- src/agent_build_kit/config_migrate.py:537 — `_rename_builders_key` rebuilds the renamed `builders` mapping with its own dict comprehension. That comprehension repeats `config.rename_builders_key` (config.py:1425), which this same change adds.
- tests/config/test_builders_stubbed_tdd_commits_default.py:96 — Task 12.1 asks for the deprecation notice to be shown by both `abk config` and `abk doctor`. The test drives only `abk config`. `abk doctor` is covered only indirectly: it reads the same `config.deprecations(path)`, which the test does assert (doctor.py:1750).
- docs/configuration.md:393 — The renamed `stubbed_tdd_commits: true` line pushes its `#` comment two columns past the comment column of the lines below it. The abk-config skill (SKILL.md:222) has the same misalignment.
