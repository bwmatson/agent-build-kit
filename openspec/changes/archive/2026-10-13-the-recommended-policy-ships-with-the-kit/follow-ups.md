## From `the-recommended-policy-ships-with-the-kit/1`

- The list of classes in UNCOVERED is still written out by hand beside PROBE_CLASSES in runtimes/acp.py. A drift test catches the two lists diverging. A shared constant for the probe classes that are not spellings would remove the second copy without making recommended_policy import acp (the builder declined this as point 1.4, and the reason holds).
## From `the-recommended-policy-ships-with-the-kit/3`

- src/agent_build_kit/runtimes/policy_apply.py:353 — A missing section is inserted after the last content line of the top-level mapping. When that last value is a keep-chomped block scalar (`note: |+` followed by trailing blank lines), the inserted lines end up inside the scalar's kept blank lines. The parse-back check then refuses the file with a message calling it 'a defect in the merge, not in your file'.

## From `the-recommended-policy-ships-with-the-kit/4`

- src/agent_build_kit/cli/policy_cmd.py:149 — `_show_configuration` now takes a parameter named `entry` (the RuntimeConfig), and the comprehension `own = [entry for entry in held.deny if entry not in wanted]` reuses that name for a deny string.

## From `the-recommended-policy-ships-with-the-kit/5`

- Task 5.6 names the abk-pipeline skill as the place that lists init's policy flags, but that skill lists none. They are listed in the abk-config skill's `runtime policy` row, and the builder updated that row: it now covers `--run-policy-fix` with the kit's fix, `abk policy apply` and `abk policy patterns`. The task text should be corrected when this change is archived.
- When the dry-run preview is refused or cannot be read, init now prints `abk: <error>` to stderr instead of indenting it on stdout under the step. That is consistent with `abk policy apply`, but init's other errors use the `abk init:` prefix. If the difference matters, add a prefix parameter to `preview`/`write_recommended`.
