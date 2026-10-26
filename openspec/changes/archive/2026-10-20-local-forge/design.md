# Design

## The forge

The forge implements the same Protocol as the code-host forges over a file in the state directory
that holds, per repo, each pull request's number, head, base, title and body, state, review notes,
replies and decision. It is chosen by the repo's `forge` setting; a remote cannot name it, so it is
never inferred. It needs no host facts.

The Protocol is larger than the pull request calls: it also has the attributes `implemented`, `client`, `requires`, `ci_name` and
`description_limit`, and the methods `merge_guard`, `comment_exists`, `pr_files`, `pr_changes`, `check_access`, `access_fix`,
`set_exclusive_label`, `rerun_checks` and `failed_check_logs`. The local forge implements every one (no client, nothing required,
access always fine), each has an entry in `forges/operations.py`'s `OPERATIONS` table saying how it is repeated, and `register` wraps
the forge in `ResilientForge` like the others, so a missing entry fails the table's own test.

Operations that have no meaning locally — labels, drafts, commit statuses, check reruns, check logs,
remote branch deletion and stacks — are accepted and do nothing, with `supports_stacks` false so units
serialise per repo as they do on hosts without stacks.

## Reading the state

Listing returns each pull request with the conversation ids, comment bodies and review decision taken
from the review store `ui-review` writes, reusing `ReviewStore` and the UI-review source (`with_ui_review`) that wraps
`forge.list_prs`, so the poller and everything after it work unchanged.

## Merge

A pull request is merged when its branch tip is contained in the trunk, or when the patch identity of
its change is found in the trunk (a squash or rebase onto the trunk). The check runs in listing and
reports the state the poller already understands.

## No remote

Where the pipeline pushes to, fetches from or compares with the remote's trunk, a local repo uses its
own trunk branch and a local branch for each unit. The places that assume `origin` are `push_target` in `restack.py`, the
per-unit fetch in `wiring.py`, `fetch_all` in `cli/pipeline.py`, `local_ref` in `units.py` and the dev-stack base ref in
`wiring.py`. The push gate that requires the approved commit
still applies. Where there is a remote the behaviour is as before.

## What an agent can read

`abk pr view` and `abk pr diff` print the local pull request and its diff read-only. They are the
commands the forge declares as allowed reads, and they do not overlap its denied commands.
