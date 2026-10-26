# acceptance-agent-gets-its-own-state-store

The acceptance tests that run a real agent below pytest give it a scratch home with links to the person's
configuration and credentials, so its session store is opened (the agent refuses its production store under a test
process) and holds nothing of the person's; a precondition fails at the first agent step when the session is not
listed, and a refused resume says why.
