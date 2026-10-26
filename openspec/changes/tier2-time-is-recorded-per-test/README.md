# tier2-time-is-recorded-per-test

An e2e-test run of 12 to 61 minutes now says where the time went. The result posted for the unit lists the slowest tests, each phase (setup, call, teardown)
on its own, headed by the three slowest; a test of the framework's own live suite also splits its time into agent steps by role, the scratch pipeline's
checks and everything else; and each duration is a histogram sample with bounded labels (marker, test file, phase), never a unit id.
