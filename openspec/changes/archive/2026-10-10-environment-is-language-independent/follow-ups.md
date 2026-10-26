## From `environment-is-language-independent/1`

- docs/init.md:165 says init writes lock files into limits.generated_files. The design and the new docs/configuration.md example treat those entries as redundant with inputs.lock. Settle this when group 3 moves environment detection into the profiles.
- docs/init.md:165 — docs/init.md still says init writes the lock files it finds into `limits.generated_files`. The new example in docs/configuration.md and the design both say lock files do not belong in that list, because sizing already takes them from the environments' `inputs.lock`.

## From `environment-is-language-independent/2`

- A person still needs to amend the planning change. Its spec scenario says a pattern leaving the repository 'fails loading', and its design says 'a path outside the repository was never meaningful here'. Both should record the one-release grace that the code now gives a literal `..` input. That grace loads the input with a warning, hashes it as before, and the next release refuses it.

## From `environment-is-language-independent/3`

- src/agent_build_kit/init/scaffold.py:263 — No test covers the explanatory comment on the fill-into-an-existing-abk.yaml route: neither the planning block nor the per-repo block that `fill_missing_environment` now writes with `_note(...)`. The builder said so. Only `dump_with_notes` is tested.
- src/agent_build_kit/cli/init.py:398 — `abk init --dry-run` prints `dump(config)` under the heading '# abk.yaml as it would be written', but the real write at scaffold.py:512 now uses `dump_with_notes(config)`.
