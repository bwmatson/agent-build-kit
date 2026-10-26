# serial-chat-tests-run-in-parallel

Ten chat-serving test modules are marked serial and run in a second, single-process pass that
costs about a minute of every whole-suite run. Measured, none of them fails beside the others;
the reason given for the marker (a session id on a command line is seen by every server on the
machine) is real only because several modules reuse one constant id. This change gives each test
its own id, guards against reuse, and takes the marker off.
