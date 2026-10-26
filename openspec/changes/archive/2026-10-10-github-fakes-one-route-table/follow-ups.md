## From `github-fakes-one-route-table/1`

- tests/forges/test_github_route_table.py: the seeded-pull test covers only GET .../pulls/16/reviews. The other routes that now go through `_no_record` have no test for the seeded case: PATCH pulls/N, the review-by-id read, review comments, reply, files and the issue comment POST. A parametrised version over those routes would pin each one.
- tests/forges/github_host.py: `page_size or 100` and the `elif ... or page_size` refusal both treat `page_size=0` as unset. An explicit 0 is silently made 100, and over a state it is not refused. Use `page_size is not None` for both checks.

## From `github-fakes-one-route-table/2`

- The guard (`routes_outside_the_table`) catches path literals starting with `/repos/` or `/graphql`, `Route()`/`_route()` calls, and `.path` compared with a literal. It would miss dispatch spelled as `seen.path.endswith("/jobs")` or a regex without the `/repos/` prefix. That is acceptable as a heuristic for the task, but the changelog's line that 'a test fails if a route is answered anywhere else' is stronger than what the guard checks.
- tests/forges/github_host.py:81 — A host built over a state refuses pulls, labels and page_size with ValueError, but it quietly merges `jobs`, `job_logs` and `draft_refusal` into that shared state. So `GitHubHost(state=server.state, draft_refusal=...)` also changes what the `FakeGitHub` sharing that state answers.
- tests/forges/test_github_route_table.py:61 — The REMAINING cases compare the host with the server, but `FakeGitHub.respond` sends every request through a `GitHubHost`. Both sides run the same handler, so the comparison proves the table serves the route (`unrouted == []`) and that the reply survives the HTTP round trip. It does not prove that the stack, job or mutation answers have the shape the forge client parses.
- tests/forges/github_host.py:98 — `answer` is re-exported through a second import block, `from tests.forges.github_routes import (answer as answer,)`, separate from the main import of the same module.
