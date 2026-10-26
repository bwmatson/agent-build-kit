# tier2-tests-have-their-own-time-limit

A test that carries the tier-2 marker runs under its own, much longer time limit, so the sixty seconds that catch a hung unit test do not
fail every live-stack acceptance test, each of which builds a unit with a real agent and takes minutes.
