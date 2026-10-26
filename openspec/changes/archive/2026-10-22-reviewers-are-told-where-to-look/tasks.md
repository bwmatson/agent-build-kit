# Tasks

Acceptance: none — every behaviour here is reply parsing, a prompt, pull request text composed by pure functions over stored facts, a setting, and a commit message, each proved by a unit-test over fake replies, fake units and temporary directories; nothing a consumer drives is built beyond what those tests drive, and nothing decides a state, a hold or a merge from the text.

Priority: 1

## 1. [agent-build-kit] [unit-test] The review reply carries a focus list and a skippable list

Done when an approving reply's two lists are parsed with the bounds the spec names without ever raising, and the lists are stored with the approval's description and read back from a record written before this change as empty. Estimate: about 330 changed lines.

Needs: review-policy-and-verdict-recorded-in-shadow group 9 — the brief shows the verdict and the reviewer's classification, and sets the verdict record's brief flag

- [x] 1.1 Test: in `tests/pipeline/test_review_brief_parse.py`, a reply whose description carries a focus list and a skippable list is read with each entry's place and reason and the focus order kept; a focus entry's reason that names one of the four kinds is kept with that kind and any other reason is kept as written with no kind; more than five entries in either list keeps the first five; entries with a blank place or, for the skippable list, a blank reason are dropped; an over-long entry is cut; a place in both lists stays in the focus list only; a list that is not a list, a reply that is not JSON, and a reply with no description each read as empty lists, the reply's `approved`, `findings`, `needs_human` and `escalate` are read as before, and none of it raises.
- [x] 1.2 Test: in `tests/pipeline/test_unit_store_brief.py`, an approval stores the two lists with the description and they round-trip through the store, a later approval of the same unit replaces them, and a record written before this change reads with both lists empty.
- [x] 1.3 Add the two lists to the reviewer's description and to `parse_verdict` in `pipeline/stack_runner.py`, and the storage to `Description` and `record_approval` in `pipeline/unit_store.py`.

## 2. [agent-build-kit] [unit-test] The review prompt asks for the lists and the unit's drivers lead the focus list

Done when with `review.brief` on, the review prompt asks for a ranked focus list and a skippable list inside the description and says an empty list is correct for a change with nothing to point at, and the unit's recorded drivers lead the focus list without repeating a place. Estimate: about 270 changed lines.

- [x] 2.1 Test: in `tests/pipeline/test_review_brief_drivers.py`, a unit whose recorded classification has drivers gets a focus list that begins with them in their recorded order with the reason the reviewer gave, the reviewer's own entries follow, a place named both as a driver and by the reviewer appears once, and a unit with no drivers or no recorded classification gets the reviewer's list unchanged.
- [x] 2.2 Test: in `tests/pipeline/test_review_prompt_brief.py`, the review prompt built with the brief on names the focus list, its four reasons, the skippable list and that each skippable entry needs a reason, and says a list may be empty; with `review.brief` off the prompt is identical to the prompt before this change.
- [x] 2.3 Add the instruction to the review prompt in `pipeline/wiring.py` only when the brief is on, and merge a unit's recorded drivers into the focus list where the description is stored.

## 3. [agent-build-kit] [unit-test] The pull request body opens with a Start here section

Done when `build_pr_body` opens a unit's body with the "Start here" section holding the focus list, the skippable list and a verified list composed from the unit's recorded results, followed by the recorded verdict's review tier and reason when review is enabled and a verdict exists, all ahead of "Why", and the verified list names every result as recorded or not recorded whatever the reviewer wrote. Estimate: about 420 changed lines.

- [x] 3.1 Test: in `tests/pipeline/test_pr_body_start_here.py`, a body built for an approved unit begins with "Start here" holding the focus entries with their reasons, the skippable entries with theirs and the verified list, then the tier line with the verdict's reason, then "Why"; an empty focus or skippable list is omitted from the section and the verified list is always there; with review not enabled or no recorded verdict the tier line is absent and the rest is unchanged; a unit with no description from the reviewer gets the verified list alone.
- [x] 3.2 Test: in `tests/pipeline/test_pr_body_verified.py`, a unit with a recorded red run, unit-test result and two review rounds lists each; a unit of the e2e-test kind lists its e2e-test result; a result that is not recorded is listed as not recorded and not left out; a reviewer reply claiming the tests passed changes nothing in the list; the list for the same recorded results is the same text each time.
- [x] 3.3 Add the section to `pipeline/pr_body.py` placed first, with the verified list composed from the unit's recorded results in the same module or a small one beside it, the tier line read from the recorded verdict, and the lists capped as the core changes are.

## 4. [agent-build-kit] [unit-test] The Start here section is never shrunk, and a held unit carries it

Needs: a-group-built-by-an-earlier-group-is-recorded group 1 merged — this unit's group 4 is already built by its group 3, so the stubbed build stops at the pair check until a group built by an earlier group is recorded as an empty pair; the unit must run on that merged code.

Done when the "Start here" section is never shrunk or dropped by the size fitting at any host limit and no other section pushes it out, and a unit held for a person carries the same section beside "Held for a person". Estimate: about 240 changed lines.

- [x] 4.1 Test: in `tests/pipeline/test_pr_body_start_here_limit.py`, at the smallest limit the registered forges allow, with a verification output, a description and a restack note each far over it, the "Start here" section is present whole, the body is within the limit, and the other sections are what shrank; with every list at its cap the section alone leaves room for the fixed sections at that limit.
- [x] 4.2 Test: in `tests/pipeline/test_pr_body_start_here_held.py`, a unit held for a person with open points carries the "Start here" section and the "Held for a person" section, in that order relative to the rest, and the same section is built for it as for an approved unit.
- [x] 4.3 Make the section a required, unshrinkable section in `pipeline/pr_body.py`, and build it for a unit held for a person as for an approved one.

## 5. [agent-build-kit] [unit-test] A setting turns the brief off, and the verdict record says it was carried

Done when the `review` section accepts `brief` defaulting to true, with it false the body is built exactly as before this change and the review prompt does not ask for the lists, and opening or updating a body that carries the section sets the unit's verdict record `brief` to true with a failure to do so logged and never delaying the body. Estimate: about 450 changed lines.

- [x] 5.1 Test: in `tests/config/test_review_brief_setting.py`, a workspace with no `brief` loads it as true, `false` loads, a value that is not a boolean fails naming the key, and an unknown key beside it still fails as before.
- [x] 5.2 Test: in `tests/pipeline/test_pr_body_brief_off.py`, with `brief` false a body built for a unit with lists, a verdict and a held section is byte for byte the body the layout before this change gives, and with it true the same unit's body differs only by the "Start here" section and the tier line.
- [x] 5.3 Test: in `tests/pipeline/test_verdict_record_brief.py`, opening a body with the section sets `brief` true on the unit's record, updating the body after a later approval sets it true again, a body without the section leaves it false, a unit with no record is left with none and logs nothing worse, and a state directory that refuses the write is logged while the body is still written and the pull request still opened.
- [x] 5.4 Add `brief` to the `review` section's model in `config.py`, make the prompt, the body builder and the record update read it, call the record update from the code that opens or updates a unit's pull request body inside a guard that logs and swallows any error, and document the key in `docs/configuration.md`, the `abk-config` skill and the `abk init` template.

## 6. [agent-build-kit] [unit-test] Build commits say why

Done when the `test:` and `feat:` commits a unit's build makes carry a one- or two-sentence body composed from the proposal's Why and the groups' goals, the pipeline's trailers still follow it, the body is bounded and cannot be read by git as a trailer or comment, and a unit with neither a Why nor a goal commits as before. Estimate: about 420 changed lines.

- [x] 6.1 Test: in `tests/pipeline/test_commit_body.py`, for a change whose proposal Why begins with a sentence and whose group has a goal the body holds that sentence and the goal; the tests body says tests come first and fail until the implementation and the implementation body says what holds once it lands; an unreadable proposal gives the goal alone; neither gives no body; a sentence over the limit is cut at a word boundary with an ellipsis; a goal beginning `Unit: ` or a line beginning `#` is reworded so git reads it as neither a trailer nor a comment; a unit carrying groups of two changes names each change once.
- [x] 6.2 Test: in `tests/graph/test_commit_messages_why.py`, with a fake runner recording each commit message, the tests commit and the implementation commit each have the title, a blank line, the body, a blank line and the `Unit:` trailer, in that order; a unit with no body keeps the message of before this change; the commit made for a rework or a restack adaption is unchanged.
- [x] 6.3 Add the composition of a commit body from the proposal and the groups' goals to a module beside `pipeline/pr_body.py`, reusing its proposal-reading helpers, and pass the message with the body to the tests and implementation commits in `graph/nodes.py`.
