#!/usr/bin/env bash
# Benchmark for README: trivial vs heavy hooks, daemon vs direct python
set -euo pipefail

cd "$(dirname "$0")/.."

N=${1:-100}
PAYLOAD='{"toolName":"Bash","toolInput":{"command":"echo hi"}}'
PYTHON=".phaicaid/venv/bin/python"

bench() {
  local label="$1"; shift
  local START END TOTAL AVG
  START=$(date +%s%N)
  for i in $(seq 1 $N); do
    eval "$@" >/dev/null 2>&1
  done
  END=$(date +%s%N)
  TOTAL=$(( (END - START) / 1000000 ))
  AVG=$(( TOTAL / N ))
  printf "  %-45s %4dms avg  (%5dms total)\n" "$label" "$AVG" "$TOTAL"
}

echo "=== phaicaid benchmark (N=$N) ==="

# --- TRIVIAL HOOK ---
echo ""
echo "--- TRIVIAL hook (return None, no imports) ---"

cat > .phaicaid/hooks/pre_tool_use.py << 'HOOK'
def handle(payload, ctx):
    return None
HOOK

# Kill any old daemon, start fresh
pkill -f "run_daemon.py" 2>/dev/null || true
sleep 0.5
rm -f .phaicaid/run/phaicaid.sock

# Warm up daemon
echo '{}' | node bin/phaicaid.js run --event PreToolUse >/dev/null 2>&1
sleep 0.3

bench "phaicaid daemon (bash+socat)" "echo '$PAYLOAD' | .phaicaid/bin/phaicaid-run --event PreToolUse"
bench "Direct Python (no daemon)" "echo '$PAYLOAD' | $PYTHON bench/direct_hook.py"

# --- HEAVY HOOK ---
echo ""
echo "--- HEAVY hook (16 stdlib imports + sha256) ---"

cat > .phaicaid/hooks/pre_tool_use.py << 'HOOK'
import ast, email, xml.etree.ElementTree as ET, urllib.parse
import http.client, logging, csv, sqlite3, hashlib, re
import pathlib, datetime, collections, functools, itertools, typing
import json

def handle(payload, ctx):
    data = json.dumps(payload)
    h = hashlib.sha256(data.encode()).hexdigest()[:8]
    return {"hash": h}
HOOK

# Restart daemon to pick up heavy hook
pkill -f "run_daemon.py" 2>/dev/null || true
sleep 0.5
rm -f .phaicaid/run/phaicaid.sock
echo '{}' | node bin/phaicaid.js run --event PreToolUse >/dev/null 2>&1
sleep 0.3

bench "phaicaid daemon (bash+socat)" "echo '$PAYLOAD' | .phaicaid/bin/phaicaid-run --event PreToolUse"
bench "Direct Python (no daemon)" "echo '$PAYLOAD' | $PYTHON bench/direct_hook_heavy.py"

# --- Restore decorator-style hook ---
cat > .phaicaid/hooks/pre_tool_use.py << 'HOOK'
from phaicaid import tool, default

@tool("Bash")
def guard_bash(ctx):
    if "rm -rf" in ctx.command:
        return ctx.deny("Blocked dangerous command")

@default
def log_all(ctx):
    ctx.log(f"pre_tool_use: {ctx.tool_name}")
HOOK

echo ""
echo "Done."
