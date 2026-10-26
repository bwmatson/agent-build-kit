# Design

## Order

1. **Why.** The change's proposal `Why` text, cut at a paragraph boundary to a ceiling (600 characters by
   default); when cut it ends with an ellipsis and a pointer to the full proposal. A unit that builds part of
   a change says the reason belongs to the change. A joined unit gets one block per change.
2. **What this pull request does.** The goal: the "Done when" sentence under each of the unit's task group
   headings. Then the core changes: three to six behaviour-level bullets written by the reviewer.
3. The stack position, scope line, assumptions, verification, points held for a person, and what is left for
   later, as now.
4. A one-line "how this was built" and the footer. No collapsible sections: support for them on every host is
   not established.

## Where each part comes from

- **The goal.** The task group parser keeps the text between a heading and its first task, `Needs:` or
  `Independent:` line when it begins "Done when", in a new `goal` field of `TaskGroup` (empty when the group has none).
  Tags and behaviour of the parser do not otherwise change. The field is not the `done` of a review finding, which is
  a different thing that happens to share the word.
- **The Why.** The proposal in the change's directory, found the way the agents find it. Only its `Why`
  section is read. When the directory is unreadable or the section is absent the part is omitted, which
  leaves today's body.
- **The core changes.** The approving verdict has an optional `description` with a summary and a list of core
  changes. The reviewer prompt asks for text written for someone who has not read the spec: facts visible in the
  diff, behaviour first, files named only where that helps, nothing about files not changed. On approval it is
  stored with the approval; a later approval replaces it, so it describes the whole branch. A description that
  is missing or malformed is ignored, costs no round and leaves the goal alone. A push made with rounds spent
  uses the last stored description if there is one.
- **The stored description.** It is a new field of the stored unit record, empty by default. It follows the record's
  resilience rules: an empty value is not written, so a record that never had a description is unchanged on disk; a
  record written before the field existed loads with it empty; and, as the record refuses a field this release does not
  know when it holds a value, a release older than this one will refuse a record that carries one, which the change
  records as the cost of adding a field (the changelog entry says so).

## De-duplicating what is left for later

The same finding is recorded once as a summary and once as a located line. The description lists each distinct
follow-up once, preferring the located form.

## Shrinking to a host's limit

The description is fitted by the shared fitter of `fit-to-budget`, to the lowest limit any host allows. The Why, goal
and core changes are the sections of highest weight, with their smallest forms reserved first and the Why capped by its
ceiling; the follow-ups, the test output and the process lines have lower weights; whatever a section does not use goes
to the others. The ordered reduction that was here (the output's start, then the follow-ups, then the output altogether, in the
body builder's `fitted` step) is replaced by that sharing.

## Not here

The title stays as it is, and is not updated after creation. A separate step that writes the description from the
diff is a later layer if the reviewer's text proves too thin.
