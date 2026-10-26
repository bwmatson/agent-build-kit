# a-pr-that-stays-conflicting-is-moved-again

A unit in review that the host reports as conflicting with the trunk is moved again, however many times it was moved before. Today the
poller starts a conflict rework only when the answer changes to "conflicting", and it keeps the last definite answer through the host's
"undetermined" after every push, so a pull request that conflicted once and was reworked stays recorded as conflicting and a later
conflict is never news: it sits in review, stale, until a person notices. This change makes a definite, fresh "conflicting" answer
enough, remembers the head and the base tip each attempt was made at so the same unresolved conflict is not dispatched in a loop, tries
the existing restack first where the unit sits on the trunk, falls back to the conflict rework, and ends in a hold with a stated reason
when neither resolves it. `abk status` says why a conflicting unit is waiting.
