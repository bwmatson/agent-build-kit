# Design

## Context

Today the reviewer writes a `description` (a summary and three to six core changes) only when it approves, `build_pr_body` leads with
"Why" and "What this pull request does", the body's sections shrink by weight to fit the host's limit, and the build's commits are
titles only (`test: <title>`, `feat: <title>`). Review's recorded results, the unit's description and the review tier's verdict are
all stored facts the body can read; none of them is ranked for the person opening the pull request.

## Decisions

- **The reviewer writes the ranking; the pipeline writes the verification.** The reply's description gains `focus` and `skippable`
  lists beside the summary and core changes, and is still read only from an approving reply. A reviewer can say where to look and
  what is safe to skip; it cannot vouch for what the pipeline checked, and a model's claim that tests passed is exactly the
  evidence the philosophy refuses to take. So the verified list is composed in pipeline code from the unit's recorded results (the
  red-first run, the unit-test result, the e2e-test result for a unit of that kind, and the number of review rounds), and a result
  that is missing is listed as not recorded, never left out.
- **Reasons are a closed set.** A focus entry's reason is one of four kinds, a StrEnum: boundary another system depends on, behaviour
  change, hard to undo, thin test coverage. Those are the kinds the verdict floors on, so the list and the tier say the same thing.
  An entry whose reason is not one of them is kept with the reason shown as the reviewer wrote it under no kind; it is not dropped.
- **Drivers lead.** When the unit's recorded classification carries drivers, the focus list starts with them in their recorded
  order, each with the reason the reviewer gave, and the reviewer's own entries follow without repeating a place already listed.
- **Bounded and parsed defensively.** The text is a model's, so it is capped as the core changes already are: at most five focus
  entries and five skippable entries, each capped in length, blank entries dropped. A malformed list is read as empty and never
  raises; `parse_verdict` keeps its rule.
- **The section is fixed.** It is a required, unshrinkable section of `build_pr_body`'s fitting, placed first, and it is bounded by
  the caps above, so the section cannot crowd out the rest and the rest cannot push it out. The caps are sized so the section fits
  under the smallest host limit with room for the other fixed sections; the line cut that guards the limit stays the last resort.
- **Tier and reason come from the verdict, not a new decision.** The line after the lists is the recorded verdict's tier and reason,
  shown only when review is enabled and a verdict exists for the unit. A verdict that could not be computed leaves the line out.
- **Held units carry the brief.** The body is built the same way for a unit held for a person, so the section is there when review's
  rounds ran out. The "Held for a person" section keeps its place.
- **`review.brief` is a key of the `review:` section**, a Frozen-validated boolean defaulting to true, added with the change that
  reads it. Off, the body is today's layout, byte for byte, and no record is touched.
- **`brief` is set by the code that writes the body.** The verdict record is written at approval with `brief` false. When the body
  that carries the section is opened or updated on the host, the same code sets the unit's record to true, inside a guard that logs
  and swallows any failure, since the record is not an input to anything. A later approval rewrites the record with false and the
  next body update sets it again, so the flag always reflects the body the person last saw. It is true when the section is present
  in the body, which it is whenever the setting is on.
- **Commit bodies are composed, not asked of a model.** A commit's body is one or two sentences: the first sentence of the proposal's
  Why for the change the unit builds, and the goal ("Done when") of the groups the commit covers. The `test:` commit's body says the
  tests come first and are red until the implementation; the `feat:` commit's says what now holds. A change with no readable Why
  gives only the goal, and a group with no goal gives neither: the commit is then the title alone, as before. The pipeline's own
  trailers (`Unit:`, `Adopted-From:`) still follow the body.

## Risks

- **A ranking that is confidently wrong.** A person may skip what mattered because the list said so. The skippable entries each
  carry their reason, and the calibration change measures whether the focus list matches what people actually changed; until that
  data exists the section is a convenience and no gate reads it.
- **A prompt that makes the reviewer pad the lists.** The prompt asks for entries only where they are true and says an empty list is
  correct for a change with nothing to point at; the caps bound the damage.
- **The section filling a small host's limit.** Azure DevOps takes fewer characters than GitHub; the caps and a test at the smallest
  limit pin the section's size.
