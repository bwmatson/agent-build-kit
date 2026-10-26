# tests-run-without-warnings

The test that makes twenty asks of the usage reading from several processes stops forking a multi-threaded test runner, which the parallel run reported as
a `DeprecationWarning` four times per run and which can deadlock a child. Its askers start with the `spawn` method and run from a helper module that
rebuilds what the old children inherited. The pytest options turn that warning into a failure, so it cannot come back unseen.
