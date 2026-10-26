# the-recommended-policy-ships-with-the-kit

The recommended deny list for a build agent moves into agent-build-kit. Today it lives in the agent's own repository, which
the kit may not have: the kit only checks an agent and can run an installation's `policy_fix`. After this change the kit
carries the recommendation as data (the command globs that refuse each forbidden class across spellings, with the sample
commands that test them), prints it for any agent (`abk policy patterns`), shows how an agent's configuration compares
(`abk policy show`), and merges it into a known agent's own configuration safely (`abk policy apply`). `abk init`'s policy
step then has a fix of its own to offer when the installation configured none.

Priority 1. Specs only so far: nothing is built, ticked or started. Build it after `init-asks-which-runtime` group 4
(the policy step this change gives a built-in fix). The design is `design.md`; what the first known agent's repository
does with its own copy afterwards is a follow-up there, not part of this change.
