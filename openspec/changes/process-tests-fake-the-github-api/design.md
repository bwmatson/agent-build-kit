# Design

## The seam

The address is a setting, not a constructor argument: the tests start `abk tick` as a subprocess, so
the only channel in is the environment. `GitHubForge` passes it to githubkit's `base_url`, and
`abk doctor`'s credential check calls the same address, so a machine pointed at an Enterprise host is
checked against it. A trailing slash is tolerated. The default is unchanged, so nothing else moves.

## The fake host

A real server on a free local port rather than a transport in the subprocess, because the subprocess
is the real CLI and builds its own client. It is built on the in-process host the forge tests already
have (`tests/forges/github_host.py` and the recorded answers), so the process tests and the unit tests
speak one set of wire shapes and a payload recorded from GitHub is fixed in one place. It keeps its
state in memory and exposes it to the test: pull requests created, comments and reviews written by
the test, merged. It answers the routes the forge uses and refuses an unknown one with a 404 the test
output names, instead of an empty success, so a route the forge starts calling shows up as a failure
here rather than as a quiet pass.

The server checks the `Authorization` header against the token the stand-in `gh auth token` prints,
so a request that goes out without the credential fails the way it would on the host.

## The fake gives a rework what GitHub gives it

The first e2e-test run found that the fake gave a rework a review but no inline comment, so the agent replied to the
review's own id, which GitHub refuses. The fake models both: a review written by the test may carry an inline comment, with
its own id, path and line, listed at the pull request's comments; a reply to a comment id is accepted and appears in the
thread; a reply to an id that is not an inline comment is a 404. It also serves a review by id. Any other route the forge
calls in the flows these tests drive is served from the recorded answers, found by running the first test and reading what
the fake could not route. A route that is not served is a failure that names the route, in every test of the module, from a
teardown check, so it cannot pass quietly in the tests that do not look.

## What stays faked as a command

`gh auth token` stays a script on `PATH` because the credential still comes from it, and the agent's
own `gh pr view` reads are not part of the forge. Both are unchanged.
