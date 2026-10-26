## From `e2e-tests-before-merge-are-optional/1`

- `with_e2e_before_merge` (src/agent_build_kit/init/scaffold.py) always adds the commented `# e2e_before_merge: required` line, even when the dumped `global_limits` already sets `e2e_before_merge` to something other than the default. Uncommenting the line would then give a duplicate key that `yaml.safe_load` resolves silently. `abk init` never sets the value today, so nothing triggers this yet. A future caller that renders an edited config could skip adding the line when `key_at(..., 'e2e_before_merge', indent=len(indent))` finds the key already in the section.

## From `e2e-tests-before-merge-are-optional/3`

- In `open_pr`, the guard that records DEFERRED is spelled `state.e2e and not runs_e2e(state)`, but the guard that posts the status is `unit.tier == TestTier.E2E_TEST and runs_e2e(state)`. Both describe the same fact. Since `runs_e2e` already implies `state.e2e`, the status guard could be just `runs_e2e(state)`, so the two read alike.
