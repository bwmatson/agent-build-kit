## From `local-forge/1`

- LocalForge.identity hashes `repo.path.expanduser().resolve()`. A relative `path:` in abk.yaml therefore gives a key that depends on the current working directory. Repo paths are never joined to the planning root anywhere (`Installation.checkouts` only expands `~`), so in practice they are already absolute or relative to the working directory. Even so, a key that is persisted in `local-prs.json` should not shift with the working directory. When group 2 touches identity, consider resolving against the planning root, or documenting that local repos need an absolute path.
- `LocalForge.list_prs` calls `units.all()` once per pull request inside `review_of`. Reading the units once, and indexing them by `(pr, branch)` before the listing, would avoid re-scanning the store for every pull request in a repo with many units.

## From `local-forge/2`

- src/agent_build_kit/forges/local.py `_seen` docstring: change '(a squash)' to '(a squash or a rebase)' to match `_in_trunk` and docs/code-forges.md.
- src/agent_build_kit/forges/local.py:344 — The `_seen` docstring still says the change is found in the trunk 'by patch identity (a squash)'. `_in_trunk` and docs/code-forges.md now also count a rebase.

## From `local-forge/3`

- tests/integration/test_local_forge_unit.py:14 — The module docstring still says 'Needs an agent speaking the protocol', which describes the ACP runtime the test no longer uses. The test now runs on Claude Code only.
- tests/integration/test_local_forge_unit.py:124 — The environment is built by copying os.environ without GH_TOKEN and ABK_GH_TOKEN, written inline. tests/forges/process_host.py:34 (`process_env`) uses the same expression.
