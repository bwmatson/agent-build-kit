# Proposal

## Why

A unit in review covers two situations a reviewer must tell apart: checks still running, so the pull
request is not yet worth reading, and checks passed, so it is ready. Today the pipeline cannot say which,
because the poller keeps only the names of failing and cancelled checks and drops the rest. A check that
is still pending is "waiting, not failing" on both hosts, and then is not recorded at all.

## What Changes

- **One list of checks:** a pull request carries a list of checks, each with a name, a status
  (`passed`, `failed`, `cancelled` or `pending`) and an optional link, replacing the separate
  failing and cancelled name lists. Each forge maps its host's words into those statuses; the poller
  and everything after it use only these.
- **Fits both hosts:** GitHub check runs, Azure DevOps pull request statuses (the latest posting
  per context) and Azure DevOps build-policy evaluations all become checks; a cancelled build is told
  from a failed one as now.
- **A derived `checking` status:** a unit in review whose checks are pending, or whose pull request
  was pushed moments ago and has none yet, reads `checking`; with its checks passed (or a repo that
  has no checks, after a short wait) it reads `in_review`. It is derived, not stored, and changes
  nothing the pipeline does.
- **Visible:** the status command, the graph and the state label show it, and a unit that is
  checking is listed with its pull request link as one awaiting review is.

## Impact

- agent-build-kit: the pull request model, both forges, the poller's snapshot and its readers, the
  state vocabulary and the status output. Depends on `dependents-follow-their-parent` group 1, which
  edits the same vocabulary module.
