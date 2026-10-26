# command-output-to-files

An agent that runs a long command writes its output to a file in an ignored scratch
folder and reads what it needs from that file with `tail` or `grep`, instead of piping the
output away and running the command again to see more of it. The full test suite then runs
once per round, not once per question. The files belong to one agent run: no agent reads
another's output, and each agent runs its own commands.
