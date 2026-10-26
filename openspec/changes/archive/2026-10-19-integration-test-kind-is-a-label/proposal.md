# Proposal

## Why

The two kinds of test abk knows are `unit-test` (one module's behaviour, in the ordinary suite) and `e2e-test` (the real local stack,
serialized on one host). Most of what a change adds sits between them: behaviour that crosses modules or files, still checked in the
ordinary suite with no live stack. Authors have no word for it. They tag it `unit-test`, which hides how wide the group's tests are, or
reach for `e2e-test`, which wrongly takes the stack lock and the scheduled run.

The user chose a third tag, `integration-test`, as a **label only**. It records how wide a group's tests are so people, the planner and
later the review work can read it, and it changes nothing about how abk builds, checks or verifies a unit.

## What Changes

- **`[integration-test]` is a group-heading tag** beside `[unit-test]` and `[e2e-test]` (the old `tier1` and `tier2` spellings stay readable as
  they are). `TestTier` gains the member `INTEGRATION_TEST = "integration-test"`; the heading reader, `abk tags`, `abk status` and plan
  validation accept and list it.
- **It behaves as `unit-test` everywhere**: the same command and checks, no e2e lock, no `local/e2e-test` status, not in the scheduled e2e
  run, in none of the e2e-only lists. It is not tied to the pytest `integration` marker or to `tests/integration/`, and the documents say so.
- **Kinds have a width**: `unit-test` < `integration-test` < `e2e-test`. A unit built from several groups takes the widest kind among
  them, where today it is `e2e-test` or `unit-test` and a middle label would be lost.
- **Joins**: a `unit-test` and an `integration-test` unit or group may be joined; `e2e-test` still never joins either. The planner's prompt
  and its schema example say so.
- **Calibration pools `integration-test` with `unit-test`**, so the new label does not split the samples a ratio is learned from.
- **Left alone**: `[acceptance]` stays `e2e-test` only; `[integration]` (without `-test`) and `tier3` stay refused, naming the three tags.
- **Elsewhere in the pipeline of changes**: the wording in the rename change's unbuilt groups (rules text, prompts, documents, skills, the
  changelog) and the review-policy change's class and floors are edited in those changes, not here.

Out of scope: driving CI, or any selection of tests, from the label. A later change may; this one makes no promise about it.

## Impact

agent-build-kit only (the planning repository's glossary and runbook mention the tag but hold no behaviour). The split into groups follows
the code: the enum and tag reading, then the unit tier and joins, then calibration, then the tests that list kinds. A stored `units.json` or
`planned.json` may now hold `"tier": "integration-test"`; nothing outside abk reads those files. The archived `test-kind-compat`
requirement that says the type has two values is modified here.
