# Tasks

Acceptance: none — a recovery rule inside the push path; tier-1 tests with real
git repositories prove it.

## 1. [agent-build-kit] [tier1] Adopt a host branch that holds the same work

Done when a unit whose branch the host holds at the same change, in rewritten
commits or at an older restack, is pushed without a person editing the store,
and a genuine disagreement still stops it.

- [x] 1.1 Test: a host branch rewritten to different commits with the same
      change is adopted: the recorded push becomes the host's head and the
      approved head is pushed with a lease on it.
- [x] 1.2 Test: a local branch restacked onto a newer trunk (the recorded push
      is not an ancestor) against a host holding the older form of the same
      work replays nothing and pushes.
- [x] 1.3 Test: a host branch with a change the local branch lacks, which does
      not combine with local work, raises `StaleRemote` naming the host's head.
- [x] 1.4 Test: a host head that is a plain descendant of the recorded push
      still replays local-only commits as before.
- [x] 1.5 Compare the diff ids against the base in `adopt_host_head`, record the
      host's head with `record_push`, and choose the commits to replay with
      `git cherry`; log which of the three outcomes applied.
- [x] 1.6 Describe the rule in `docs/architecture.md` where the push lease is
      explained, and add a changelog entry.
