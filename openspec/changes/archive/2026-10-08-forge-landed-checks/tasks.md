# Tasks

Acceptance: none — host-specific reads behind the forge seam; tier-1 tests over recorded payloads
and a fake transport prove them.

## 1. [agent-build-kit] [tier1] The reads that make a create safe to repeat

Needs: forge-retry-layer group 1 merged — the operation table and wrapper these reads serve

Done when a lookup raises when it cannot tell, a duplicate create returns the existing pull
request, a comment's existence can be asked on both hosts, and a failed follow-up after a create
no longer fails the unit.

- [x] 1.1 Test: GitHub `find_pr` returns the pull request, returns nothing on an empty answer, and
      raises on a transport error; Azure's still does; callers treat the raise as the host being
      unavailable.
- [x] 1.2 Test: a GitHub create refused as a duplicate returns the existing pull request, while a
      base-missing refusal is still base missing; the Azure duplicate error maps the same way.
- [x] 1.3 Test: `comment_exists` over recorded listings finds a comment by marker and exact body,
      finds a reply under its parent, returns nothing when none matches, and returns the id for
      own-post recording, on both hosts.
- [x] 1.4 Test: `stack_of` answers membership for the stack create and add checks.
- [x] 1.5 Test: Azure's body update after a create and its commit-status post are advisory: a
      failure is contained and the unit continues, as GitHub's.
- [x] 1.6 Make the changes in both forges, declare the operations and their landed reads in the
      table, and update the callers of `find_pr`.
- [x] 1.7 Update `docs/code-forges.md` and the changelog.
