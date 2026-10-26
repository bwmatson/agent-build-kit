# claude-code-account-per-installation

An installation can run its Claude Code work on its own account. The account is named by one existing setting, the config directory
(`CLAUDE_CONFIG_DIR`, or `ABK_CLAUDE_HOME`, in the installation's `.env` or the process environment), and no abk.yaml key is added.
Today that setting reaches only the sessions page, and a `.env` value never reaches a `claude` the pipeline starts. This change makes
the one setting the account for the whole pipeline: every `claude` abk starts is told it, the usage guard reads that account's
credentials and global state file and never the default account's, a cached reading from another account is discarded, the
allowance calibration restarts on a change, the sessions page, `abk install-skills --user` and `abk doctor` follow it, and the docs
say how to set it up.
