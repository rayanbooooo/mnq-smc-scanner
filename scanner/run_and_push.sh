#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."

LOG=/tmp/mnq-scanner.log
echo "=== $(date) ===" >> "$LOG"

python3 scanner/scan.py >> "$LOG" 2>&1

if ! git diff --quiet -- site/data/status.json; then
  git add site/data/status.json
  git commit -m "scan: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG" 2>&1
  git push >> "$LOG" 2>&1
  echo "pushed update" >> "$LOG"
else
  echo "no change, skipped push" >> "$LOG"
fi
