## From `pipeline-environment/1`

- scaffold.py fill_missing_environment: match a repo's entry only at the indent of the direct children of `repos:`. Today a nested key with the same name in an earlier repo can take the insertion.
- Add a unit-size test for a lock entry outside its root (`../framework/uv.lock`) that is matched by its file name, which is the case the change to file-name matching was made for.
- A lock file name listed by one repo is also left out of other repos' units, because `actual_lines` does not know which repo a change belongs to. Scoping this needs its callers changed.
- src/agent_build_kit/init/scaffold.py:187 — The fill looks for a repo's entry with `_key_line(lines, str(name), start=section + 1, ...)`. That accepts `name:` at any indent inside `repos:`, so it can match a nested key in an earlier repo that has the same name as a later repo.
- src/agent_build_kit/config.py:94 — Lock entries are now matched by file name, but no test covers the case that motivated it: a lock path outside its own root, such as `../framework/uv.lock`. The existing `web/pins.lockdata` test already passed before this change.

## From `pipeline-environment/2`

- `in_progress_label` in pipeline/units.py still compares against the literal string "environment" and not `Cause.ENVIRONMENT`, to avoid an import cycle. If the cause's stored value is ever renamed, that comparison will silently stop matching. A test that pins the label for `Cause.ENVIRONMENT` would catch it.
- Add a tick-level test for the heal path failing: sync and the re-check both fail, and the recorded hash is unchanged.
- tests/cli/test_tick_environment.py:111 — The new test only covers a failed sync on the changed-input path. The heal path, where the check fails, the second sync also fails, and the check still fails, is not tested for keeping `previous.hash`.

## From `pipeline-environment/3`

- `_changed_from_base` in src/agent_build_kit/pipeline/environment.py now compares at `git merge-base <base> HEAD` using git object ids (`rev-parse <point>:<path>` against `hash-object`). No test pins either behaviour. Two would: one where the base gains a manifest change after the unit branched and a failing `check` is still classed as the environment's, and one where a CRLF input left unchanged by the unit does not count as changed.
- When a unit is stacked on a parent branch that edited a manifest, a failure counts as the child unit's own, because the parent's edit shows as a difference from the base. Decide whether that is intended, and add a test with a stacked parent that edits a manifest.
