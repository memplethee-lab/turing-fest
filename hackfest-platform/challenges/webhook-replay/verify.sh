#!/usr/bin/env bash
# Run by the judge worker, inside the locked-down grading container, with
# the team's submitted files already copied over ./editable.
#
# Must print exactly one JSON line to stdout as its last line of output:
#   {"passed": bool, "checks": [{"check": str, "pass": bool}, ...]}
# and exit 0 on pass, nonzero on fail. The worker parses that last line and
# ignores everything else, so ts-node's own noise on stderr is harmless.
set -euo pipefail
cd /app
npx ts-node tests/hidden_tests.ts
