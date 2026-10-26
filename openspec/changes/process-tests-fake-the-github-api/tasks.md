# Tasks

Acceptance: group 3 runs `test_graph_acp_unit.py` and `test_acp_build_unit.py` against the fake host
with the real ACP agent and both pass.

## 1. [agent-build-kit] [unit-test] The GitHub API address is a setting

Done when the forge and doctor call the address `ABK_GITHUB_API_URL` names, and the default is
unchanged.

- [x] 1.1 Test: with no setting a forge call and the doctor check go to `https://api.github.com`;
      with the setting they go to that address and none to `api.github.com`; a trailing slash gives
      no doubled slash in the path.
- [x] 1.2 Add the setting to `settings`, pass it to the GitHub client's base address and to
      `abk doctor`'s credential check.
- [x] 1.3 Document the setting in `docs/code-forges.md` and add a changelog entry.

## 2. [agent-build-kit] [unit-test] A fake GitHub host for process tests

Done when a test can start a server that answers the forge's routes over HTTP from the recorded
answers, with its state driven by the test.

- [x] 2.1 Test: the server serves each route a unit's life uses (find by head, create, read,
      comments and reviews, labels, merge state) with the recorded shapes; a create then a lookup
      finds the pull request; a duplicate create is refused as GitHub refuses it; a test-written
      review and a merge show in the next read.
- [x] 2.2 Test: a request without the token gets 401, and a route not served gets a 404 whose body
      names the method and path.
- [x] 2.3 Test: the forge, pointed at the server through the setting, creates and finds a pull
      request, and the credential it sends is the one the stand-in prints.
- [x] 2.4 Write the server on top of `tests/forges/github_host.py` and the recorded answers, with a
      fixture that starts it on a free port and stops it.

## 3. [agent-build-kit] [e2e-test] [acceptance] The process tests use it

Needs: acp-runs-without-a-model group 1 merged — every node over the ACP runtime failed at once with a missing model argument, so these tests could not get past building

Done when the two ACP tests pass against the fake host with the real agent, every route the forge calls in them is served
by the fake, and no process test fakes the forge as a `gh` script beyond `gh auth token`.

- [x] 3.1 Test (`local_stack`): run `test_the_unit_is_built_reviewed_and_pushed_through_the_runtime` first and read its tick
      output and the fake's `unrouted()` list before changing anything; every route it lists is served by the fake, or the
      test fails naming the route (an e2e-test failure keeps only the last four thousand characters, so run it).
- [x] 3.2 Test: a review written by the test with an inline comment gets its own id, path and line and is served at the
      pull request's comments; a reply to that id is accepted, appears in the thread and returns the review id and node
      id; a reply to an unknown id, including the id of a review, is a 404, as on GitHub.
- [x] 3.3 Test: the fake serves a review by id, and each other route the flows reach (rerunning failed jobs, stacks,
      branch protection) that 3.1 shows they call, from the recorded answers.
- [x] 3.4 Test: both integration test modules assert `host.unrouted() == []` in a module-level teardown, so a route the
      fake does not serve fails every test in the module and names the route.
- [x] 3.5 Test (`local_stack`): `test_graph_acp_unit.py` builds the unit, opens pull request 7 on the fake host, resumes it
      into rework on an inline review comment the test writes, sees the agent's reply in that comment's thread, and ends at
      merge.
- [x] 3.6 Test (`local_stack`): `test_acp_build_unit.py` reaches `in review: PR #7` with the fake host holding the pull
      request.
- [x] 3.7 Add the inline review comment, the reply and review-by-id routes and any route 3.1 shows, and the teardown check.
- [x] 3.8 Replace the `gh` stand-in in both tests, and in `test_telemetry_stack.py`, with the fixture, keeping only
      `gh auth token` as a script, and update each file's docstring.
- [x] 3.9 Document in `docs/architecture.md` how a process test fakes the host.
