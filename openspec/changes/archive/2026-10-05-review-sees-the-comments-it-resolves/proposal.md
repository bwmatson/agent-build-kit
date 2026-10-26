# Proposal

## Why

A unit goes back for rework for one of three reasons: the pipeline's own review
asked for changes, a check failed, or a person commented on the pull request.
The rework agent is given the person's words in its prompt and answers each
comment in a JSON reply. Then the review runs again to judge the rework.

That review is told about *earlier review rounds* (`_earlier_rounds`: what its
own rounds asked, and what the builder said it did), but not about the person's
comments, which were never a review round, nor the builder's replies to them.
Its tools are `git diff`, `git log` and `git show`, so it cannot read the pull
request either. It is asked to judge a change against a request it cannot see.

The result is a review that checks the diff against the original tasks and its
own earlier findings, and can approve a rework that misses what the person
actually asked, or object to a change the person requested.

## What Changes

- **The runner hands the review the comments, deterministically.** When a
  review follows a rework triggered by a person, its context carries the
  reviewer's comments as the rework saw them, and the builder's reply to each
  (the same JSON the runner posts after the push). No agent fetches them.
- **The review is told what it is judging.** The note says whether each comment
  was done, answered with a reason, or left, and asks the review to check the
  builder's reply against the code, as it does for its own earlier findings.
- **Agents may read the pull request, read-only.** The review agent is granted
  its repo's forge read commands (`gh pr view` and `gh pr diff` on GitHub,
  `az repos pr show` on Azure DevOps), as build agents already are, for
  anything the note does not carry. Merging, voting, posting and the raw API
  remain refused on every repo.
- **Nothing the agents read can change the host.** Comments are untrusted text
  from the host; the note labels them as the reviewer's words, not instructions
  to the review.
