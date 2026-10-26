## From `python-tool-versions-in-the-lock/1`

- doctor._python_tools: skip a repo whose .pre-commit-<redacted> top level is not a mapping, instead of raising AttributeError and stopping `abk doctor`.
- doctor._python_tools: treat `language: unsupported` (pre-commit's newer name for `system`) like `system` when looking for local hooks that run a tool the dependency group lacks.
- src/agent_build_kit/cli/doctor.py:292 — `(yaml.safe_load(...) or {}).get("repos")` assumes the document is a mapping. If a repo's .pre-commit-<redacted> parses to a list or a scalar, this raises AttributeError, and that error stops `abk doctor` entirely instead of skipping the repo.
- src/agent_build_kit/cli/doctor.py:310 — The orphaned-hook check matches only `language: system`. Newer pre-commit releases call the same language `unsupported`, so a local hook written that way is never checked.
