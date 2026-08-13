#!/bin/bash
# Runs one scan cycle and pushes the result if it changed. Invoked every 5 min by
# the com.rayan.mnq-smc-scanner LaunchAgent -- keep this independent of any
# particular chat session, it must survive on its own.
set -euo pipefail

REPO_DIR="$HOME/mnq-smc-scanner"
PYTHON3="/usr/local/bin/python3"
GIT="/usr/bin/git"

cd "$REPO_DIR"

"$PYTHON3" scanner/scan.py

if ! "$GIT" diff --quiet -- site/data/status.json; then
  "$GIT" add site/data/status.json
  "$GIT" commit -m "scan: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null
  "$GIT" push origin main >/dev/null
fi
