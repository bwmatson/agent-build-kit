# Proposal

## Why

A unit stacked on another is built only after its predecessor is in review, and is checked against
that predecessor only while it runs. Once it is in review nothing looks at its predecessor again.
When the predecessor goes back to rework, is rebased onto a moved base, or fails with new commits
on its branch, the dependent stays `in_review` with a ready pull request on top of a base that is
being rewritten. A reviewer sees a unit that looks mergeable and is not.

The pull request also stays ready for review whenever a unit leaves review for any reason: a
pull request is drafted when its unit runs and published when it returns to review, but not when it
goes back to planned. And a running unit is one word for a first build, a rework for feedback and a
rebase, which hides why a dependent is waiting.

## What Changes

- **An in-review unit follows its predecessor:** each pass, a unit in review whose same-repo
  predecessor's branch is changing goes back to `planned` with the cause `upstream_went_back` and a
  note naming the predecessor; its approval, branch, pull request and thread are kept. It is
  released when the predecessor is back in review or merged, and restacks onto the predecessor's
  new head.
- **When a branch is changing:** the predecessor is not in review or merged and its branch has
  commits beyond the last pushed head, or it is being rebased, or it is itself waiting on a changing
  upstream. A rework that only answers comments leaves the head unchanged and does not move its
  dependents.
- **A pull request is a draft whenever the pipeline is not waiting for a reviewer:** running or
  planned units with an open pull request are drafts; a unit in review is ready.
- **Running says what it is doing:** a derived status `rebasing` for a conflict or moved base,
  `reworking` for review or check feedback, `running` otherwise, shown in status, the graph, the
  label and the notes.

## Impact

- agent-build-kit: the state vocabulary, the draft follower, a predicate and a pass in the
  tick, and the status, graph and label output. No change to the unit store's states.
