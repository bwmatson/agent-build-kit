# Proposal

## Why

A CI run of the kit on 2026-10-15 UTC carried annotations on all three jobs, and the `test` job printed a warnings summary. Read on their own, none of
them failed the run, but each is a notice that something will stop working or already hides a defect:

1. **Node 20 actions.** "Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: actions/checkout@v4,
   actions/setup-node@v4, actions/setup-python@v5, astral-sh/setup-uv@v3". The runner forces them onto Node 24 today; the forcing is a stopgap and a
   later runner release may remove it, at which point the jobs fail at their first step.
2. **`DEP0040` `punycode` warnings.** Node prints `The punycode module is deprecated` under the setup and post steps of the same actions, in every job.
3. **`ubuntu-latest` moves.** "The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026". The next run after that date may run on a
   different operating system, with different system libraries and a different default toolchain, for no reason in the diff.
4. **Cache-service warnings.** `Failed to restore: Cache service responded with 400` and `Failed to save: <h2>Our services aren't available right
   now</h2>`. GitHub's service was failing at that time (the same run's `integration` job failed on a fetch for what is probably the same reason, see
   the sibling change `ci-fetches-openspec-once`). This is not something the repository causes or can fix.
5. **A pydantic serializer warning in the `test` job.** Six parametrizations of
   `tests/graph/test_held_state_plain_text.py::test_a_populated_state_carrying_the_nodes_values_encodes_no_blocked_type` print
   `UserWarning: Pydantic serializer warnings` with `PydanticSerializationUnexpectedValue(Expected tuple[...]` for the fields `groups`, `review_rounds`,
   `last_findings`, `deferred`, `pending_replies`, `given_comments` and `commits`, each given a list where the model declares a tuple. It is the only
   warning in the run's summary (6 warnings, all this one).

Items 1 to 3 and 5 are ours and are fixed here. Item 2 is expected to go with item 1. Item 4 is recorded and left.

## What Changes

- **Every action moves to a Node 24 release, pinned exactly.** `actions/checkout` to v7.0.1, `actions/setup-node` to v7.1.0, `actions/setup-python` to
  v7.0.0 and `astral-sh/setup-uv` to v10.3.0, each written as its full release tag. A floating major is not used: `astral-sh/setup-uv` publishes no
  major tag since v8, so `@v10` does not exist, and one rule for all four is simpler than one per action.
- **The runner is pinned.** `runs-on: ubuntu-24.04` in all three jobs, the image the runs used already. The move to Ubuntu 26 becomes a deliberate change.
- **A unit test guards both.** It parses every `.github/workflows/*.yml` and fails on an action below the first release that runs on Node 24, on an
  action that is not in its table, on a `*-latest` runner and on a floating action reference.
- **The serializer warning is fixed where it starts, and fails the suite if it returns.** The test builds its state through validation, so tuple fields
  hold tuples, and a test fails on any `PydanticSerializationUnexpectedValue` that the state it builds raises.
- **The policy is written down** in `AGENTS.md`, where the guard's failure message points.

## Impact

- agent-build-kit: the three workflow jobs in `.github/workflows/ci.yml`, one new `tests/test_ci_workflows.py`, one test and its helper under
  `tests/graph/` and `tests/checkpoint_types.py`, `pyproject.toml` (`[tool.pytest.ini_options]`) and `AGENTS.md`. No framework source and no changelog
  entry (design: "No changelog").
- Spec: `ci-workflows`.
