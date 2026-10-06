#!/bin/zsh
# Runs every paid comparison. Keys are read from .env in the repo root (gitignored) and never written to results.
# Each step resumes from saved responses, so rerunning after an interruption costs nothing.
# Rerunning into this results/ directory reuses the saved responses; use a fresh checkout for a fresh run.
set -euo pipefail
cd "$(dirname "$0")"
KEYS="${JEV_PILOT_KEYS:-.env}"
[[ -f "$KEYS" ]] || { echo "Missing $KEYS (see .env.example)"; exit 1; }
set -a; source "$KEYS"; set +a
export TYPESAFE_API_KEY="${TYPESAFE_API_KEY:-${TYPE_SAFE_API_KEY:-}}"
PY="${PYTHON:-.venv/bin/python}"
[[ -n "${TYPESAFE_API_KEY:-}" ]] && $PY src/incidents.py jev
for ARM in $($PY -c "import sys; sys.path.insert(0, 'src'); from llm_client import available_arms; print(' '.join(available_arms()))"); do
  $PY src/comparator.py routing --arm $ARM
  $PY src/incidents.py llm --arm $ARM
  $PY src/comparator.py world --arm $ARM
done
