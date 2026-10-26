## From `dry-cleanup/1`

- src/agent_build_kit/telemetry.py:220 — `telemetry.count` still accepts a callable attribute and its docstring still promises one. The two `abk.checks.failures` calls this branch removed (graph/nodes.py) were the only callers that passed a callable (`check=lambda: failed_check(...)`), so that path is now dead and no test covers it.
- src/agent_build_kit/pipeline/stack_runner.py:995 — `_open_ids` is a one-line wrapper with one caller and no docstring, unlike its neighbours `_open_entries` and `_render_open`.

## From `dry-cleanup/3`

- pr_body._change_path now goes through changes_dir_under, which calls expanduser on specs_dir. A specs_dir written as `~/...` therefore becomes an absolute home path in the pull request link, where before it stayed literal. Both forms make a broken repo-relative link, so behaviour is effectively the same. If someone ever relies on a home-relative specs_dir, the link builder should decide on purpose which form it wants.
