# Tasks

Acceptance: none — prompts and one classification, with no surface a consumer drives; the
prompt content and the satisfied path are both provable at tier 1.

## 1. [agent-build-kit] [tier1] Build and review this unit, not the ones after it

Done when both prompts name the boundary and say why, a reviewer's later-group finding
does not block, and a unit whose groups are already implemented ends satisfied rather than
failed.

- [x] 1.1 Test: a build run's prompt carries its own groups and the later units' groups
      distinctly, and instructs it to implement only its own, with the reason.
- [x] 1.2 Test: a review's prompt carries the same boundary, and its instruction to find
      everything and sweep the domain is preserved for the unit's own groups.
- [x] 1.3 Test: a unit with no commits of its own whose tier-1 checks pass is recorded
      satisfied — groups ticked, dependents released, no pull request opened, not in the
      failed list; the judgement uses the branch and the checks, not the run's report.
- [x] 1.4 Test: no commits and failing checks is still a failure; commits plus a
      already-implemented remainder still goes to review.
- [x] 1.5 Add the boundary to the build and review prompts, passing the later units'
      groups alongside the unit's own.
- [x] 1.6 Add the satisfied classification where an empty step is judged, with the state,
      the ticking and the release of dependents.
- [x] 1.7 Say in `docs/architecture.md` where units and review are described, and in the
      `abk-pipeline` skill's states table, that a unit builds only its own groups and that
      satisfied means the work arrived another way.
- [x] 1.8 Test: a unit that becomes satisfied while holding an open pull request has the reason
      posted first and the pull request closed after, and the posted text names the groups it
      covered, says they were implemented elsewhere, and names where the work landed when the
      graph can determine it.
- [x] 1.9 Test: no agent call is made on that path — neither to judge it nor to write the text.
- [x] 1.10 Test: a satisfied unit with no pull request opens none and posts nothing; a failure to
      post or to close is recorded and leaves the unit satisfied.
- [x] 1.11 Add closing a pull request to the forge interface, with the host's implementation
      behind it, since it can open, status and reply but not close.
- [x] 1.12 Compose the reason where pull request bodies are composed, and post-then-close it where
      a unit becomes satisfied.
- [x] 1.13 Note in `docs/architecture.md`, where the forge's surface is described, that closing is
      part of it, and in the `abk-pipeline` skill that a satisfied unit's pull request is closed
      with the reason on it.
