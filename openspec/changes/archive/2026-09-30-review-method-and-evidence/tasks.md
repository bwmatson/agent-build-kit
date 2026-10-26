# Tasks

Acceptance: none — this is the pipeline's own review loop, with no surface a
consumer drives; what proves it is tier-1 tests whose reviewer returns each
verdict shape in turn.

## 1. [agent-build-kit] [tier1] A review with a method, and findings the loop can read

Needs: converging-review group 1 — it reshapes the same verdict, round note and
review prompt; this builds on the verdict it leaves and must keep every shape it
accepts.

Done when the review prompt names its angles and its evidence bar, a verdict's
findings are a list that the builder's feedback is rendered from, each later
round is shown every earlier required finding whole and answers it by id, and a
verdict in the earlier prose shape still works unchanged.

- [x] 1.1 Test: a verdict carrying a findings list is parsed into findings with
      file, optional line, summary, consequence, what done looks like and
      required; a verdict with only prose feedback parses exactly as before.
- [x] 1.2 Test: a verdict that approves while listing a required finding is not
      an approval; one that approves with only optional findings is.
- [x] 1.3 Test: the text rendered from a findings list puts required before
      optional and gives each its location, consequence and what done looks
      like, and that text is what the unit stores as feedback and what the
      rework prompt carries.
- [x] 1.4 Test: a required finding returned without a consequence still blocks,
      is rendered marked as having none stated, and is counted in the log.
- [x] 1.5 Test: more than five optional findings are cut to the first five with
      the number left out logged, and required findings are never cut.
- [x] 1.6 Test: a recorded round keeps its findings with ids and the commit the
      reviewer judged, and a store holding rounds recorded before this change
      still loads and renders them as prose.
- [x] 1.7 Test: the next round's note names the commit the previous round
      judged and lists each earlier required finding whole with the builder's
      answer; when the note must be shortened, whole findings are left out,
      those reported fixed first, with the number stated, and none is truncated.
- [x] 1.8 Test: a later verdict that approves while an earlier required finding
      is reported open, or is left unanswered, is not an approval; one that
      reports every earlier finding fixed or declined-and-accepted may approve.
- [x] 1.9 Test: the review prompt directs the reviewer to enclosing functions,
      to what removed lines enforced and to callers and callees, and tells it
      to re-check each candidate; and the reviewer's tools remain read-only with
      no way to start another agent.
- [x] 1.10 Add the finding model and extend the verdict parser, keeping its
      existing return for current callers and every verdict shape
      `converging-review` accepts.
- [x] 1.11 Render findings to the feedback text, apply the optional cap, and
      record findings, ids and the judged commit on each round.
- [x] 1.12 Rewrite the earlier-rounds note to list findings whole by id with
      the judged commit, and read the verdict's answers to earlier findings.
- [x] 1.13 Add the angles, the candidate check and the evidence bar to the
      review prompt, and the findings list to the reply it asks for.
- [x] 1.14 Update `docs/architecture.md` where the review loop is described,
      and the `abk-pipeline` skill where it says what a reviewer returns.
