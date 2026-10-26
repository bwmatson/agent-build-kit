# Tasks

Acceptance: none — this adds a type, a table of old and new spellings and the reading of both at three edges, each proved by a unit-test over temporary files, fake plans and fake stores; nothing a consumer drives is built beyond what those tests drive.

Priority: 1

## 1. [agent-build-kit] [tier1] The names, the enum and the reading of the heading tags

Done when `TestTier` exists with the values `unit-test` and `e2e-test`, the compatibility module holds the table and the notice text, a heading tagged with either spelling is read as the same kind (the old one with a notice), and `abk tags` and `abk check` report each old tag they read. Estimate: about 330 changed lines.

- [x] 1.1 Test: in `tests/test_compat_names.py`, the table maps `tier1` to `unit-test` and `tier2` to `e2e-test` in tags, settings keys (`tier1_*` to `unit_test_*`, `tier2_*` to `e2e_*`, `tests.tier2_marker`, `tier2_runtimes`, `tier2_splits`), stored values, state-file names and metric names, and a lookup of a new spelling returns it unchanged.
- [x] 1.2 Test: in `tests/pipeline/test_work_graph_test_kind_tags.py`, headings tagged `[unit-test]` and `[e2e-test]` are read as the two `TestTier` members; `[tier1]` and `[tier2]` are read as the same members and each produces one deprecation notice naming the new tag and the group; an unknown tag is refused as before, listing the new spellings; `abk tags` prints the new spellings for both.
- [x] 1.3 Add the compatibility module with the table and the notice text, and the `TestTier` enum; have the heading parser read through the module, and have `abk tags` and `abk check` print its notices. (This is the first part of the former single task that also wired the settings loader, the store, `abk config` and `abk doctor`; those are task 2.4.)

## 2. [agent-build-kit] [tier1] The old settings keys and stored values are read as the new ones

Done when the old settings keys and stored values are read as the new ones, no old spelling is ever written, and `abk config` and `abk doctor` report each old spelling they read. Estimate: about 320 changed lines.

- [x] 2.1 Test: in `tests/config/test_test_kind_settings_aliases.py`, each old settings key loads as its new key with the same value and validation, `abk config` prints only new keys and one notice per old key read, a file holding the old and the new spelling of one setting is refused naming both, and a per-repo `tests` block is read the same way.
- [x] 2.2 Test: in `tests/pipeline/test_unit_store_test_kind_values.py`, a store and a plan record written before the rename read with the kind as `TestTier`, and the next write of either holds only the new value; a stored unit with an unknown kind is refused as before.
- [x] 2.3 Move the stored and planned unit's `tier` field to a `TestTier`-typed field in `pipeline/units.py` and `pipeline/unit_store.py`, still serialized under the old key name until the slices rename the readers, and read both keys.
- [x] 2.4 Have the settings loader and the store read through the compatibility module, and have `abk config` and `abk doctor` print its notices. (This is the second part of the former single task that added the compatibility module.)
