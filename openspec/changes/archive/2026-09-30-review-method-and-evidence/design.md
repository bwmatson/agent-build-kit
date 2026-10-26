# Design

## Where this sits

`review_once` runs a round: commit, ask the reviewer, `parse_verdict`, then
either record the approval or store the feedback and run a rework. The reviewer
gets an optional note (predecessor, earlier rounds, and after
`converging-review` the budget and the stake) followed by the standing
`REVIEW_PROMPT`. It has read-only tools: Read, Grep, Glob and `git diff`,
`git log`, `git show`. None of that structure changes. `REVIEW_TOOLS` does not
gain the agent tool, and a test says so.

This builds on `converging-review`'s verdict — approval with follow-ups, the two
escalations — and must keep every shape that change accepts.

## The angles

Added to `REVIEW_PROMPT` as a short numbered method ahead of the existing
bullets, worked in order in the one pass:

1. **Every hunk, and the function around it.** A defect in an unchanged line of
   a touched function is in scope: the change re-exposes it or leaves it.
2. **Everything removed.** For each line deleted or replaced, name what it
   enforced — a guard, an error path, a validation, a test of a real case — and
   find where the new code re-establishes it. A return value whose meaning
   downstream has changed counts: the line is the same and what it causes is
   not.
3. **Every caller and callee.** For each function the diff changes, find its
   callers and check each against a new precondition, a changed return shape, a
   new exception, an ordering dependency. Where several functions make the same
   check, confirm the change reached all of them.

Then the check: before keeping a candidate, re-read the code it points at, and
drop it if the code already handles it. This replaces nothing a verifier
subagent would do that one careful reader cannot; it is there so a candidate
formed from the diff is tested against the file.

The toolchain-neutral wording matters: the prompt is sent for every profile, so
the angles are stated without a language's pitfalls.

## The evidence bar

A required finding carries a `consequence`: the input or state and the wrong
result. Three kinds of finding have no crash to describe and are still
legitimately required, so the prompt says what their consequence is:

- a convention the repo documents — the rule and where it is written;
- a test that would pass either way, or that the task asked for and is missing —
  the wrong behaviour that would go unnoticed;
- a doc the change makes false — the sentence and what is now true.

**A required finding with no consequence still blocks.** The parser does not
demote it. Failing open on a reviewer's omission would let a real defect through
because a field was left empty, and that is the wrong direction for a gate. It
is rendered to the builder with "(no consequence stated)", and the run log
counts them, so a reviewer that habitually omits it is visible.

## The verdict

```
{"approved": false,
 "findings": [
   {"file": "src/pkg/units.py", "line": 182,
    "summary": "waiting_on does not look through a satisfied dependency",
    "consequence": "with c/1 planned and c/2 satisfied on it, c/3 is built on main without c/1's work",
    "done": "iterate through_satisfied() as base_of does; test c/1 in planned, running, failed, held",
    "required": true}
 ],
 "earlier": [{"id": "1.2", "status": "fixed"}],
 "feedback": "",
 "needs_human": false}
```

- `Finding` is a frozen model in the module that owns the review loop's types.
  `line` is optional; `done` is what the existing prompt calls "say what done
  looks like", now a field.
- `parse_verdict` keeps its return for existing callers and gains the parsed
  findings. **`feedback` alone is still a valid verdict**: an older-shaped reply
  is read exactly as now, with no findings.
- `approved: true` with a required finding in the list is a contradiction and
  is read as not approved — the same direction as an unreadable reply.
- `render_findings(findings)` produces the text: required first, then optional,
  each with its id, location, summary, consequence and done. That text is what
  is stored as the unit's feedback, sent in the rework prompt and written to a
  pull request, so nothing downstream of the loop changes shape.
- Optional findings beyond five are dropped at parse time, in the order the
  reviewer ranked them, and the log says how many. Required are never dropped.

## Ids and later rounds

The loop assigns `<round>.<n>` to each required finding when it records the
round. A round's record gains the findings and the commit the reviewer judged;
the existing `asked` and `response` stay, so a store written before this change
still loads and an old round renders as it does now.

The earlier-rounds note changes in two ways:

- It lists each earlier required finding whole — id, location, summary,
  consequence — instead of the first 4000 characters of the round's prose. If
  the note must be shortened, whole findings are left out oldest-first among
  those already reported fixed, and the note says how many; a finding is never
  cut part-way. A round recorded as prose only keeps today's rendering.
- It names the commit the previous round judged and tells the reviewer that new
  findings come from `git diff <that commit>..HEAD`, or from older code only
  with a reason it was not visible before — the instruction it has today, now
  with the range to apply it to.

The verdict's `earlier` answers each listed id with `fixed`, `open`, or
`declined` (the builder gave a reason and it holds). An id left unanswered is
treated as `open`. A round may not approve while an earlier required finding is
`open`; that is read as not approved. This gives `converging-review`'s
repeated-disagreement escalation something exact to count: the same id `open`
after the builder declined it.

## What is deliberately not done

No second agent run. The cost of a multi-angle review is its fan-out, and the
measured problem here is rounds, not recall within a round at any price. If the
angles in one pass prove insufficient, a verifier step is a later change with
its own cost argument.

## Testing

Through `review_once` and `parse_verdict` with a reviewer double returning each
shape: findings only, prose only, both, a contradiction, an unanswered earlier
id, more than five optional. The prompt's content is asserted where it is
behaviour the loop depends on — the angles are present, the note names the
judged commit — not by matching its wording.
