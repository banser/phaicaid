#!/usr/bin/env python3
"""Direct Python hook execution (no daemon) — the baseline."""
import json, sys

def handle(payload, ctx=None):
    """Minimal hook identical to the daemon-served ones."""
    return None

if __name__ == "__main__":
    payload = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    result = handle(payload)
    print(json.dumps({"ok": True, "result": result}))
