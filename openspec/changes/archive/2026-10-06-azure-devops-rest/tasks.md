# Tasks

Acceptance: none — a transport change behind the forge seam; tier-1 tests over recorded
responses and a parity check against the old behaviour prove it. A live listing against
a scratch project is a manual check noted in the pull request.

## 1. [agent-build-kit] [tier1] Azure DevOps over typed REST

Needs: forge-http-transport group 1 merged — the transport, credentials and error rules this builds on

Done when every Azure DevOps operation runs over REST with typed models, listing no
longer starts subprocesses, and the forge's results are unchanged.

- [x] 1.1 Test: recorded responses parse into the models; an unknown field is
      ignored; a malformed body raises an error naming the endpoint.
- [x] 1.2 Test (parity): over recorded responses for a project, `list_prs` returns the
      same `PullRequest` fields the old behaviour does: merged only on completed,
      changes requested from votes, definite mergeability, newest status per genre and
      name, system comments filtered, cancelled versus failing.
- [x] 1.3 Test: a paged list follows every continuation token; reads for many open
      pull requests stay within the concurrency bound; a closed pull request costs only
      the list call.
- [x] 1.4 Test: create, update (with the no-op base comparison), reply, comment,
      labels, statuses, files, abandon, draft and branch deletion each make the
      expected REST call through a mock transport and none starts a subprocess.
- [x] 1.5 Test: the PAT and the credential-source paths both authenticate; an HTML
      sign-in body is an authentication error.
- [x] 1.6 Write the models and the REST client, port the operations, remove
      `pipeline/az.py` and the `az`-wire fakes, and drop the `permitted_commands`
      carve-out if nothing else uses it.
- [x] 1.7 Update `docs/code-forges.md` and `docs/architecture.md`, the dependency
      notes, and the changelog.
