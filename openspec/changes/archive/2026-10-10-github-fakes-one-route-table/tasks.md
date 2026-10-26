# Tasks

Acceptance: none — test support; the existing suites of both hosts are the proof.

## 1. [agent-build-kit] [tier1] The table, with the routes the two hosts share

Needs: process-tests-fake-the-github-api group 3 merged — the reply and review-by-id handlers and inline comments it adds to `FakeGitHub`, which this makes single

Done when the pull, review, comment, status and label routes are answered from one table over one state by both hosts.

- [x] 1.1 Test: the in-process host and the HTTP server give the same answer from the same state for each of the pull
      list, create, find, update, review, review-by-id, comment, reply, status and label routes, and a review with an inline comment written
      through the server is seen by the in-process host.
- [x] 1.2 Test: a scripted route overrides the table for its test only, and an unserved route is a recorded 404.
- [x] 1.3 Move those routes into the table and the shared state, derive the pull node on read, and delete the second copy
      of the state and its synchronisation.
- [x] 1.4 Document the table in `docs/architecture.md` and add a changelog entry.

## 2. [agent-build-kit] [tier1] The remaining routes, and the guard

Done when every route is in the table and a guard stops a second place from appearing.

- [x] 2.1 Test: the draft mutations, check and job routes, stacks and branch protection (served by neither host before this) are answered from the table
      by both hosts.
- [x] 2.2 Test (guard): a handler registered or a route answered outside the table fails the test naming it.
- [x] 2.3 Move the remaining routes into the table and delete the old handlers.
- [x] 2.4 Update `docs/architecture.md` and add a changelog entry.
