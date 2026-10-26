# Tasks

Acceptance: none — pure text and recorded host limits; tier-1 tests prove each behaviour.

## 1. [agent-build-kit] [tier1] The shared cuts and the fitter

Done when text is cut and sections are fitted by one module, with unused allocation passed on.

- [x] 1.1 Test: each cut returns an unchanged text that fits, never exceeds the size, keeps the head, the tail or both on the
      boundary asked, and closes an open code fence and collapsible block; the general description cut keeps its existing
      tests as a wrapper.
- [x] 1.2 Test: the fitter renders everything in full when it fits, reserves smallest forms first, drops from the lowest
      weight up without dropping a required section, respects ceilings and weights, and never exceeds the budget.
- [x] 1.3 Test: a short section gives its unused share to the others, so a long section of equal weight receives its share
      plus the remainder; repeating gives the same result.
- [x] 1.4 Add the cuts and the fitter, and turn the general description cut into a wrapper over them.
- [x] 1.5 Document the module in `docs/architecture.md` and add a changelog entry.

## 2. [agent-build-kit] [tier1] The lowest limit, once, and the description on the fitter

Done when a description is fitted once to the lowest limit across the hosts and keeps what it kept.

- [x] 2.1 Test: the effective limit is the lowest declared across the registered hosts and changes when a host with a lower
      one is added; the same inputs give the same description for two hosts that declare different limits.
- [x] 2.2 Test: a description that fits is unchanged; the output's tail is kept; follow-ups are whole items followed by a
      count; the verdict and headings survive; with no follow-ups the output gets the room, and with no output the follow-ups
      do; the tests that assert these today pass.
- [x] 2.3 Test: neither host's create nor update cuts a description itself (the `fit_description` calls in each host's
      create and update are gone), and the body the pipeline passes to `build_pr_body` is fitted to the effective limit,
      not to the limit of the one host the unit's repository uses.
- [x] 2.4 Work out the effective limit in the base of the forge layer, build the description from sections, fit it once where
      it is handed to a forge (replacing the single host's `description_limit` passed to `build_pr_body`), and remove the
      host's own cuts.
- [x] 2.5 Update `docs/architecture.md` and `docs/code-forges.md` and add a changelog entry.

## 3. [agent-build-kit] [tier1] Test output, earlier rounds and statuses

Priority: 4

Needs: flaky-tests group 1 merged — both edit the tier 1 command and failure assembly

Done when a unit's saved failure names the failed tests, and the other assemblies share the fitter.

- [x] 3.1 Test: the test output is a section per command, a failed command weighing more; for a log with seven failed tests
      over the budget all seven identifiers and their error lines are present, and a profile that cannot read the failed
      tests keeps the tail.
- [x] 3.2 Test: earlier review rounds over their size keep open findings in full and say how many others were left out, as
      they do today.
- [x] 3.3 Test: each host declares a status description limit; a status description is fitted to the lowest status limit
      across the hosts, and no host cuts the string it is handed, so a description within the lowest limit reaches every
      host unchanged.
- [x] 3.4 Build the test output, the earlier rounds and the status descriptions on the fitter; add the `status_limit`
      attribute to the forge protocol and each host, and remove the raw slices in each host's status call.
- [x] 3.5 Update `docs/architecture.md` and add a changelog entry.

## 4. [agent-build-kit] [tier1] The remaining cuts use the shared ones

Priority: 4

Done when the raw slices that cut text to a size use the shared cuts and keep what they kept.

- [x] 4.1 Test: each of the remaining cuts (the failure tail, the command output tails, the CI job log tail, the resolver's
      diff, the one-line notes and the error excerpts) gives the same result through the shared cut as before.
- [x] 4.2 Move each to the shared cut.
- [x] 4.3 Add a changelog entry.
