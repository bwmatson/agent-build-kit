## From `repo-wide-guards-treat-planning-content-as-data/2`

- src/agent_build_kit/cli/scrub_store_cmd.py:63 — The dry run still labels each count `path(s)` and `HELP` (line 25) still reads "replace home-directory paths in the stored unit text", though the count and the rewrite now include issue references; the `_counts` docstring ("count of home paths per field") is stale the same way.
- tests/installation_leaks.py:87 — ANECDOTE now builds on ISSUE_REFERENCE, whose lookbehind no longer excludes `/`, so the leak guard flags `owner/repo#N` wherever the owner is not a fixture owner or `<redacted>`. Before, any slash-prefixed reference passed. The suite passes today, but the guard is now stricter, and the commit does not say so.
