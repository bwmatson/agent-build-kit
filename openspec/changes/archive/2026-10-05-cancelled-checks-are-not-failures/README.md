# cancelled-checks-are-not-failures

A check the host cancelled says nothing about the code. The poller read it as a
failure and sent the unit back for rework, twice in a row during a host
outage, spending a rework on a pull request with nothing wrong. Cancelled
checks are re-run by the runner instead, a bounded number of times.
