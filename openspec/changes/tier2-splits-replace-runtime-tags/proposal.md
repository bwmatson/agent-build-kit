## Why

`tier2-tests-are-tagged-by-runtime` solved the kit's own problem (the tests that drive an ACP agent need a metered model, the ones that drive Claude do not) by building it into the
framework: markers whose names must match `runtimes.<name>`, `tests.runtimes_blocked`, `tests.runtimes_allowed` and `tests.e2e_runtimes`, `abk e2e-test block|unblock`, and, in the
change that reads a provider's usage, a provider on the runtime. A consumer cannot use any of that unless it splits its tests by agent runtime. What a repo needs to say is how its e2e-test
runs are split and which splits are held, for any reason: a metered model, a GPU host that is down, a licence server, a stack that is slow. A runtime is one way a repo may split, not the
way.

Six of that change's units are merged and two are running, so the runtime naming is already in `main` and will be in two more units before anything can be changed. Rewriting history is not
possible and stopping the pipeline is not wanted. This change migrates the merged code to splits, and the groups of that change that have not started are rewritten in place to the
generic wording and wait for this one.

## What Changes

- **A split is declared, not derived.** `tests.e2e_splits.<name>` with a `marker` and an optional `hold`, at the top of `abk.yaml` and, replacing it, under a repo's own `tests`. The
  tests in no split are `rest`, always declared, reserved, holdable. The three lists `runtimes_blocked`, `runtimes_allowed` and `e2e_runtimes` are removed with no alias: they were never released.
- **The profile translates the selector.** One builder makes the selection over the declared splits; the python profile turns a `marker` into the `-m` expression it gave for the
  runtime tags, lists a selection's tests without running them (`list_tests`), and says which selector kinds it supports; a profile that supports none runs whole and says so.
- **Membership is exclusive and checked by the framework.** A test selected by two splits is found by listing and reported by the new `abk e2e-test check`, which also reports unknown
  selectors and failed listings. The kit's collection-time plugin is no longer the mechanism and stays only as its repo-local convenience.
- **The blocked set is the held set.** `e2e-held.json`; `source` is `command` or `gate`; a deadline only on a `gate` entry; `hold: true|false|unset` with the configuration winning
  (`hold: false` is what `runtimes_allowed` was). The text edit of `abk.yaml` works on a split entry's `hold` key.
- **Parking, the record and the gate carry a split.** `E2eSession`'s parked set and each failure's group, the park cause (`split_held`), `PreExisting.split` and `holding_fixes` replace
  their runtime forms; a held split records nothing and holds no other split's run. Older stored names are read.
- **The scheduled run is one change per declared split and `rest`**: `scheduled-e2e-<repo>-<date>-<split>`.
- **The kit's own splits are installation configuration.** The documents give `acp` and `claude_code` as the splits an installation declares for the kit; a test keeps every split,
  runtime and provider name out of the framework outside the provider table.

The commands `abk e2e-test hold`, `release` and `status`, the per-split gate (`gate.command`, `gate.provider`) and the kit's own test renames are built by the groups of
`tier2-tests-are-tagged-by-runtime` and `a-runtimes-provider-has-usage-windows` that have not started; those groups are rewritten to the generic wording and `Need:` this change's groups.

## Impact

- agent-build-kit: `config.py` (the `tests` block: `SplitConfig`, `e2e_splits`, the lists removed, `BASE_GROUP` to `REST_SPLIT`, `known_runtime_names` removed), `pipeline/e2e.py`
  (the selection, `TestFailure`, `E2eResult`), `pipeline/e2e_blocks.py` renamed `e2e_holds.py`, `config_text_edit.py`, `pipeline/wiring.py` (`E2eSession`, the record wiring),
  `pipeline/untouched_failures.py`, `pipeline/unit_store.py` and `graph/nodes.py` (the park cause and stored fields), `pipeline/e2e_schedule.py`, `profiles/base.py` and
  `profiles/python_uv.py` (selector kinds, `expression`, `list_tests`, `registered_selectors`), a new `pipeline/e2e_splits_check.py` and `cli/e2e_cmd.py`, the configuration,
  runtimes and command documents, the three skills, the changelog.
- It rewrites code that `tier2-tests-are-tagged-by-runtime` groups 1 to 5, 7 and 12 merged and that its groups 8 and 10 are building; it `Needs:` those two groups.
- `tier2-tests-are-tagged-by-runtime` (its planned groups) and `a-runtimes-provider-has-usage-windows` are rewritten to splits and `Need:` this change's groups.
- Priority 1: the planned groups must not be built on the runtime names, and the two running units are about to add more of them.
