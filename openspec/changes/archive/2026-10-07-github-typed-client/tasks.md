# Tasks

Acceptance: none — a transport change behind the forge seam; tier-1 tests over recorded
payloads and a parity check prove it. A live listing against a scratch repository is a
manual check noted in the pull request.

## 1. [agent-build-kit] [tier1] GitHub through a typed client

Needs: forge-http-transport group 1 merged — the credential sources, retry policy and doctor check this builds on

Done when every GitHub operation runs through the typed client, listing is one query per
page, no subprocess is started, and the forge's results are unchanged.

- [x] 1.1 Test (parity): over recorded GraphQL payloads, `list_prs` returns the same
      `PullRequest` fields as the old behaviour: state and merge time, draft, labels,
      issue comments and reviews (pending excluded), failing versus cancelled checks,
      review decision, mergeability, paging.
- [x] 1.2 Test: create and edit a pull request (with `BaseMissing` mapped from the
      response), review notes, replies returning both node ids, issue comments,
      labels with the colour and description reconcile, statuses, branch protection and
      branch deletion each make the expected call through a mock transport.
- [x] 1.3 Test: draft toggling, close, rerun of failed jobs, and the failed-job log
      extraction over recorded job logs behave as before.
- [x] 1.4 Test: stack create, add and get call the stack endpoints and a conflict is
      reported as concurrent.
- [x] 1.5 Test: one client per owner, built with that owner's credential; no
      subprocess is started by any operation; caching is off and a timeout is set.
- [x] 1.6 Add the dependency, the per-owner client, port the operations, remove the
      `gh` subprocess helpers and the exact-argument tests, and make `Forge.client`
      optional.
- [x] 1.7 Update `docs/code-forges.md` and `docs/architecture.md`, the dependency
      notes, and the changelog.
