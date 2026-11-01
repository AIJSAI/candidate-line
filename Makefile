# Candidate Line. The targets the build plan names. Each is a stub that says "not yet" and
# exits non-zero, so no tool can read a stub as a pass, until its Sunday item replaces it.
# `make trace last` passes `last` as a second goal, so `last` is a no-op target here.

.PHONY: help eval gate trace text last

help:
	@echo "make eval        run the eval cases"
	@echo "make gate        the tests, the evals and the cost line; required before done"
	@echo "make trace last  the latest call's trace"
	@echo "make text        the line in text mode"

eval:
	@echo "not yet: the eval runner lands Sunday (KICKOFF.md, item 12)"; exit 1

gate:
	@echo "not yet: make gate lands with the eval runner (KICKOFF.md, item 12)"; exit 1

trace:
	@echo "not yet: the trace store lands Sunday (KICKOFF.md, item 14); its spans are written live"; exit 1

text:
	@echo "not yet: the text-mode REPL lands Sunday (KICKOFF.md, item 10)"; exit 1

last:
	@:
