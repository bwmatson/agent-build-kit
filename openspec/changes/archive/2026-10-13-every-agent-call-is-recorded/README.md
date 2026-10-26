# every-agent-call-is-recorded

Every call to an agent leaves a row in the usage ledger, not only the unit graph's steps. A shared
helper writes the row for the conflict resolver (`restack`), the planner, the track runs, init's
research and proposal, the policy probe, the login refresh and chat, each under its own node name, and a
guard test makes a new call that records nothing fail tier 1.
