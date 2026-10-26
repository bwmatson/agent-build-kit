# test-suite-speed

Run a repo's tests across the machine's cores, so the whole suite is a
fraction of the time it takes in one process. `agent-build-kit`'s suite is
about 2,300 tests taking about 90 seconds in one process; with its tests spread
over workers it takes about 20.
