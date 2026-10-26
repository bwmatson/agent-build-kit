# flaky-tests

Stops flaky tests at three points: tests that a unit adds are run repeatedly before review, a flake in an existing
test is isolated, recorded and sent to one fix specification that every unit it blocks waits on, and the habits
that make tests flaky are ruled out by guards and by the guidance the agents are given.
