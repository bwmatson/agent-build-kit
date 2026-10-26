# Design

## Where

`restack.adopt_host_head` and the two call sites that read `pushed`
(`events` on a restack, `wiring` on the push). The decision is made there and
the result recorded with `record_push`; nothing else reads a stale `pushed`
afterwards.

## Same work

`restack.diff_id(repo, base, branch)` already hashes the changed lines of
`base...branch`, and is what carries an approval across a clean move. The host
head is fetched, and when `diff_id(base, host_head) == diff_id(base, local)` the
host's branch is the same work as ours. Nothing is replayed; the record is set
to the host's head, so the lease matches and the push puts the approved head
over it. An unexplained difference in the diff ids falls through to the replay.

## What to replay

The commits unique to the local branch are those `git cherry host_head branch`
marks as not present upstream (patch-equivalence), rather than
`rev-list last_pushed..branch`, which assumes the local history descends from
the last push. After a restack it does not. If every local commit is
patch-equivalent to one on the host, the case above applies and nothing is
replayed.

## Out of scope

A host head that adds work we do not have is not merged automatically beyond
what replaying already does, and a failed replay still stops the unit.
Rewriting history on the host is not something the pipeline does here.
