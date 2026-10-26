# one-round-per-refresh

One function, a round, does everything a tick does between "the guard allows work" and
"start what is ready": refresh from the code host, convert, plan, link, verify and archive,
then evaluate and submit. The tick runs it once at its start, and a running pass runs it
on every refresh, so the work a tick picks up is also picked up while builds run. There is
one trigger path, not two that drift.
