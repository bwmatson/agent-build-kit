## From `process-tests-fake-the-github-api/1`

- tests/forges/github_server.py:228 — `GET /pulls/{n}/files` always returns an empty list. That is enough for `pr_changes` to run without raising. A later unit that checks the size gate through the fake will need the fake to answer with the files a test sets up.
- tests/forges/github_server.py:236 — `PATCH /pulls/{n}` applies `base`, `body` and `state` but ignores `title`. Nothing calls `update_pr(title=...)` today. If something does later, the title change would be dropped without an error.
## From `process-tests-fake-the-github-api/2`

- The module-scoped `unrouted()` teardown check fails the run once, as an error on the last test, not every test as tasks.md 3.4 and design.md say. Reword the spec, or use an autouse function-scoped check.
- process_host's `gh` stand-in fails the agent's own `gh pr view`/`gh pr diff` reads; design.md says those are 'unchanged'. Align the design text or answer those reads harmlessly.
- FakeGitHub's review and inline-comment payloads are hand-built. Add recorded GitHub answers for a review and a review comment or reply, and build the fake from them.
- tests/integration/test_graph_acp_unit.py:82 — An unserved route is caught by an assert in the teardown of the module-scoped `github_host` fixture. Pytest reports that once, as an error on the module's last test, not as a failure of every test as tasks.md 3.4 and design.md describe. The same applies to tests/integration/test_acp_build_unit.py:98.
- tests/forges/process_host.py:235 — The `gh` stand-in now exits 1 for every call except `gh auth token`. That includes `gh pr view` and `gh pr diff`, which the agent is allowed to run (`GitHubForge.read_commands`). The old scripts printed `{}` for them. design.md says the agent's own `gh pr view` reads are 'unchanged'.
- tests/forges/github_server.py:312 — The review and inline-comment payloads in `_new_review` and `_new_inline` are written by hand, not loaded from a recorded GitHub answer. `tests/forges/recorded` holds no pull-request review or review-comment answers, so these shapes are not tied to anything GitHub actually sent.
