# Tasks

Acceptance: none — the review's context and tool list inside the pipeline;
tier-1 tests over the note, the prompt context and the tool list prove it.

## 1. [agent-build-kit] [tier1] Give the review the comments it is judging

Done when the review after a person-triggered rework is given the comments and
the builder's replies, and may read its pull request on its repo's host without
being able to change anything there.

- [x] 1.1 Test: a review following a rework triggered by a person's comments
      gets a context containing each `[comment N]` and its recorded reply, with
      "no reply" for a comment the builder did not answer.
- [x] 1.2 Test: a review following a rework from its own findings, or from a
      failing check, gets no comments note; the first review gets none.
- [x] 1.3 Test: the note frames the comments as the reviewer's words, and text
      in a comment addressed to the review is quoted, not obeyed.
- [x] 1.4 Test: the review's tool list carries the repo's forge read commands,
      not the other forge's, and none that write.
- [x] 1.5 Build the note from the stored feedback and `pending_replies`, add it
      to the review context beside `_earlier_rounds`, and add
      `forge_read_tools(forge)` to the review's allowed tools.
- [x] 1.6 Update `docs/unit-graph.md`'s "Who touches the code host" table and
      the review node's row, `docs/architecture.md`, and the changelog.
