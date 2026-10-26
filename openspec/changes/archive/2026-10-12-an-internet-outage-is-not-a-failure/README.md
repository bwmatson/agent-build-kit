# an-internet-outage-is-not-a-failure

When the network is down, or the model service cannot be reached or is overloaded while the rest of the network works, a unit whose agent run fails for
it is no longer failed. The runtime says so in a typed error, the unit goes back to `planned` with the cause `network_unavailable` (the whole network is
down) or `service_unavailable` (the provider, or the route to it, is down or answering 5xx or 529), keeps its thread, branch and saved feedback, waits
out the same backoff as a unit parked for the code host, and resumes at the step it stopped on. A bounded connectivity probe of the failing API host plus
a control group of other hosts, with no model call, tells the two apart; a failure carrying a 5xx or 529 status parks as `service_unavailable` up to a
bounded number of attempts. While the whole network is down, a pause marker of the new kind `network` stops a tick starting agent runs; a provider
outage is per-unit backoff only. Planning is covered too: a change whose planner call meets an outage does not use one of its planning attempts, shows as waiting and is planned again once the outage is over; a failed plan keeps its reason. The existing code-host handling is unchanged. Checks and tests that fail for the network stay a named follow-up.
