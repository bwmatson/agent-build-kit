# ci-runs-without-warnings

The kit's CI run reports no warning that the kit controls. Every action in every workflow moves to a release that runs on Node 24 and is pinned to an exact
version, the runner is pinned to `ubuntu-24.04` instead of floating with `ubuntu-latest`, and a unit test parses the workflow files and fails on an action
below its Node 24 release, on a floating runner label or on a floating action reference. The pydantic serializer warning that the `test` job prints is
fixed in the test that causes it, and a test fails if it comes back. GitHub's own cache-service warnings are recorded as not ours to fix.
