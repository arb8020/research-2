.PHONY: test test-contract test-teams test-recombined-probe campaign

SHOWDOWN_DIR ?=
MANIFEST ?= $(CURDIR)/manifest.json
FAILURE_DIR ?= $(CURDIR)/failures
SUMMARY ?=

test: test-contract test-teams test-recombined-probe campaign

test-contract:
	node test-minimize.js
	node test-subprocess.js
	node test-artifact.js
	node test-coverage.js

test-teams:
	@test -n "$(SHOWDOWN_DIR)" || { echo "SHOWDOWN_DIR is required" >&2; exit 2; }
	node test-team-pool.js "$(SHOWDOWN_DIR)"

test-recombined-probe:
	@test -n "$(SHOWDOWN_DIR)" || { echo "SHOWDOWN_DIR is required" >&2; exit 2; }
	node test-probe-recombined.js "$(SHOWDOWN_DIR)"

campaign:
	@test -n "$(SHOWDOWN_DIR)" || { echo "SHOWDOWN_DIR is required" >&2; exit 2; }
	POKEMON_RANDOM_SUMMARY="$(SUMMARY)" node run.js "$(SHOWDOWN_DIR)" "$(MANIFEST)" "$(FAILURE_DIR)"
