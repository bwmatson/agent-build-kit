## From `tier2-time-is-recorded-per-test/1`

- The e2e-test durations bullet in CHANGELOG.md has one line that runs well past the wrap width of the bullets around it ("output, so a small description never cuts the listing. Each entry also becomes a `test_time` ledger row and feeds the"). This came from resolving the rebase conflict. Rewrap it when the bullet is next touched.

## From `tier2-time-is-recorded-per-test/2`

- The two live scratch modules each define an identical module-scoped `scratch_ledger` fixture (`scratch.state / LEDGER_NAME`), next to the near-identical `Scratch` types they already duplicate. If those types are ever unified, move the fixture beside the shared type.
