# Tasks

Acceptance: none — the body is built from a unit record, a proposal and a recorded verdict; tier-1 tests with
recorded reviewer verdicts prove it.

## 1. [agent-build-kit] [tier1] The Why and the goal lead the description

Needs: fit-to-budget group 2 merged — the shared fitter and the lowest limit this uses

Done when a pull request description opens with the change's reason and the unit's goal, follow-ups appear
once, and a host's length limit still holds.

- [x] 1.1 Test: the parser keeps the "Done when" sentence under a group heading in the group's `goal`, an empty
      `goal` for a group without one, and the existing tag parsing is unchanged.
- [x] 1.2 Test: the Why section is the proposal's `Why` text, cut at a paragraph boundary to the budget with
      an ellipsis and a pointer when cut, labelled as the change's reason for a part of a change, one block per
      change for a joined unit, and omitted for an unreadable proposal or a missing section.
- [x] 1.3 Test: the goal appears under a heading for what the pull request does, and the order is Why, what,
      stack position, scope, assumptions, verification, held and left for later, with the how-built paragraph
      reduced to one line.
- [x] 1.4 Test: a finding recorded as a summary and as a located line is listed once, in the located form.
- [x] 1.5 Test: with the lowest limit any host allows, the goal and core changes have the highest weight with
      their smallest forms reserved, the Why is capped by its ceiling and cut to its smallest form before the goal or
      changes are, the other sections give up room first, and a section that does not use its share passes it on.
- [x] 1.6 Add `goal` to the group model, the Why reader, the new sections and order, the de-duplication and
      the weights, floors and ceilings of the new sections (replacing the ordered reduction in the body builder), and
      pass the inputs from the open-pull-request step.
- [x] 1.7 Update `docs/architecture.md` and `docs/code-forges.md`, and add a changelog entry.

## 2. [agent-build-kit] [tier1] The reviewer describes the branch

Done when an approving verdict's description is stored and shown, with a safe fallback.

- [x] 2.1 Test (recorded verdicts, with and without the field): the verdict parser reads a description with a
      summary and core changes and ignores a malformed one without failing the review.
- [x] 2.2 Test: an approval stores the description with the approved commit, a later approval replaces it, and
      a rework that is not approved leaves the stored one; a stored unit record with no description loads with it
      empty and is written without it, and one with a description round-trips.
- [x] 2.3 Test: the pull request description shows the stored core changes; a push with rounds spent shows the
      last stored description; with none, the goal alone is shown.
- [x] 2.4 Test: the reviewer prompt asks for a description written for someone who has not seen the spec, from
      the diff, and costs no extra model call.
- [x] 2.5 Add the verdict field and its parse, the stored description (a new field of the stored unit record, empty
      by default and omitted when empty, under the record's rules for fields another release does not know), the
      prompt instruction and the rendering.
- [x] 2.6 Update `docs/architecture.md` for the verdict and the body, and add a changelog entry that says a release
      older than this one refuses a record holding a description.
