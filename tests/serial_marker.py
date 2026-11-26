"""Test support: the word of the `serial` marker, which no test or configuration file names.

A test that cannot run beside others is isolated, not marked. `tests/exclusions.py` keeps the word
out of the tracked test and configuration files; a test that needs it as data (a command still
carrying the old selection) takes it from here, so the word stays in this file.
"""

MARKER = "serial"
