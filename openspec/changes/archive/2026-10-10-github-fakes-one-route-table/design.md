# Design

## The table

A route is a method, a path pattern and a handler. A handler takes the state and the request and returns the response, using
the recorded answers where there is one. The state holds the pull requests, their reviews and inline comments, labels,
statuses and the counters that give things ids. The pull node a listing returns is derived from that state when it is read,
so there is nothing to keep in step.

## The hosts today

The in-process host is `tests/forges/github_host.py` and the HTTP server's state is `FakeGitHub` in `tests/forges/github_server.py`.
Each keeps its own pull request state. The routes `process-tests-fake-the-github-api` group 3 adds to the server (inline review
comments, replies, review by id) exist only there, and stacks and branch protection are in neither.

## The hosts

The in-process host and the HTTP server each look a request up in a scripted override first and then in the table; a miss is
a 404 recorded as unrouted, as now. The HTTP server adds only what a server needs: the listener, the token check, and the
test-facing calls to write a review or comment and to merge, which change the state. Nothing else is in it.

## Migration

The first group moves the routes the two hosts duplicate and the state they keep twice, including the reply and review-by-id
handlers and the inline comments that `FakeGitHub` gained. The second moves the rest: the draft
mutations, the check and job routes, replies, stacks and branch protection, and deletes the old handlers. The tests of both
hosts are not edited except to import from where a thing now lives.

## The guard

A test fails if a handler is registered anywhere but the table, or if a route is answered in a host.
