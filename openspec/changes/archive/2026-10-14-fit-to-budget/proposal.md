# Proposal

## Why

A pull request description must fit what the code host allows, and the hosts differ: one allows 65,536 characters and
another 4,000. The description shrinks in a fixed order written for it: cut the head off the test output, drop follow-ups
to whole items, then replace the output, and only then does a general cut at a line boundary apply. Each step is tuned to one
section and none shares what another does not use. The limit is the host's, so the same pull request reads differently on the
two, and each host's code calls the general cut itself.

About twenty other places cut text with a raw slice. Three assemble several parts into one text: the description, the
earlier review rounds shown to a reviewer, and the test output of several commands. The saved failure of a unit is the last
four thousand characters of that output, which kept the end of the log and lost the lines that said which tests failed and
why, so six of seven failures in one run could not be diagnosed afterwards.

## What Changes

- **One module that cuts and fits text:** cuts that keep the head, the tail or both, on a line or a paragraph, and close any
  open code fence or collapsible block; and a fitter that takes sections with a size, a smallest honest form, a weight and an
  optional ceiling, and allocates a budget by sharing: a section that needs less than its share releases the rest to the
  others.
- **The limit is the lowest any host allows,** so a description reads the same on every host. The hosts declare their limits
  as facts; the effective one is worked out once, in the base of the forge layer, which also applies the fit. The hosts no
  longer cut descriptions themselves.
- **The pull request description uses the fitter,** keeping everything it keeps today.
- **A unit's test output keeps what the failure needs:** for each failed test, its identifier and its error lines come before
  passing output and tracebacks.
- **Other assemblies and cuts use the same module,** with no change in what they keep.

## Impact

- agent-build-kit: a new module, the base of the forge layer and both hosts, the description builder, the tier 2 output, the
  review prompt's earlier rounds, status descriptions, and the raw cuts elsewhere. Pending `pr-description-says-why` changes
  to use the fitter for its new sections.
