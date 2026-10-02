#!/usr/bin/env bash
# Run the NGU e2e suite. Usage: ./run.sh [pytest args...]
# Defaults to the local backend; override with NGU_BASE_URL.
set -euo pipefail
export NGU_BASE_URL="${NGU_BASE_URL:-http://localhost:8000}"
echo "Target: $NGU_BASE_URL"
exec python -m pytest "$@"
