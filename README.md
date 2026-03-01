# phaicaid

**Python Hooks for AI Coding Assistant: Interface and Daemon**

Ergonomic Python hooks for AI coding assistants, powered by a long-lived daemon that eliminates per-hook startup overhead. Write hooks with decorators, scoped handlers, and response builders — instead of parsing raw JSON payloads and constructing response envelopes by hand. A background Python daemon keeps your modules cached in memory, so hooks respond in ~12ms regardless of how many imports they use.

```python
# .phaicaid/hooks/pre_tool_use.py
from phaicaid import tool, default

@tool("Bash")
def guard_bash(ctx):
    if "rm -rf" in ctx.command:
        return ctx.deny("Blocked dangerous command")

@tool("Write", "Edit")
def protect_env(ctx):
    if ctx.file_path.endswith(".env"):
        return ctx.deny("Cannot modify .env files")

@default
def log_all(ctx):
    ctx.log(f"pre_tool_use: {ctx.tool_name}")
```

Supports **Claude Code** and **GitHub Copilot CLI**.

## Install

```bash
npm i -D phaicaid
```

## Quick Start

```bash
npx phaicaid init --target claude   # or --target copilot
```

This creates:

- `.phaicaid/` — runtime dir with Python daemon, SDK, venv, and your hooks
- `.claude/hooks.json` (or `hooks.json` for Copilot) — wired to the daemon

Edit `.phaicaid/hooks/pre_tool_use.py` and you're live. Changes are picked up instantly via inotify (Linux) or polling (macOS/Windows) — no restart needed.

## Scaffold Hooks

```bash
npx phaicaid add PreToolUse         # decorator-style template
npx phaicaid add PostToolUse        # decorator-style template
npx phaicaid add SessionStart       # simple style (no tool scoping)
npx phaicaid add PreToolUse --simple  # force simple handle() style
npx phaicaid add all                # scaffold ALL hook events at once
```

Refuses to overwrite existing files. `add all` skips any that already exist.

## Supported Events

### Claude Code (15 events registered, 2 opt-in)

| Event | When it fires | Tool scoping |
|-------|--------------|:------------:|
| `PreToolUse` | Before a tool call executes | Yes |
| `PostToolUse` | After a tool call succeeds | Yes |
| `PostToolUseFailure` | After a tool call fails | Yes |
| `PermissionRequest` | When a permission dialog appears | Yes |
| `SessionStart` | Session begins or resumes | — |
| `SessionEnd` | Session terminates | — |
| `UserPromptSubmit` | User submits a prompt | — |
| `Notification` | Claude Code sends a notification | — |
| `SubagentStart` | A subagent is spawned | — |
| `SubagentStop` | A subagent finishes | — |
| `Stop` | Claude finishes responding | — |
| `TeammateIdle` | A teammate is about to go idle | — |
| `TaskCompleted` | A task is marked completed | — |
| `ConfigChange` | A config file changes mid-session | — |
| `PreCompact` | Before context compaction | — |
| `WorktreeCreate` | Worktree created (opt-in, replaces default git) | — |
| `WorktreeRemove` | Worktree removed (opt-in, replaces default git) | — |

WorktreeCreate/WorktreeRemove replace default git worktree behavior — they are not registered automatically. Use `npx phaicaid add WorktreeCreate` to opt in.

### GitHub Copilot CLI (6 events)

| Event | When it fires |
|-------|--------------|
| `sessionStart` | Session begins |
| `sessionEnd` | Session ends |
| `userPromptSubmitted` | User submits a prompt |
| `preToolUse` | Before a tool call |
| `postToolUse` | After a tool call |
| `errorOccurred` | An error occurs |

## Decorator API

### `@tool(*patterns)` — scope to specific tools

Works in tool-scoped events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`.

```python
from phaicaid import tool

@tool("Bash")
def guard(ctx):
    """Runs only for Bash tool calls."""
    ...

@tool("Write", "Edit")
def protect(ctx):
    """Runs for Write or Edit."""
    ...

@tool("mcp__.*")
def log_mcp(ctx):
    """Regex: matches all MCP tools."""
    ...
```

Plain strings are auto-anchored (`"Bash"` becomes `^Bash$`). If the pattern contains regex metacharacters, it's used as-is.

### `@default` — fallback handler

```python
from phaicaid import default

@default
def catch_all(ctx):
    """Runs when no @tool handler matched."""
    ctx.log(f"unhandled: {ctx.tool_name}")
```

### Dispatch rules

- Decorated handlers are tried first. If any `@tool` matches, it runs and `@default` is skipped.
- If no `@tool` matches, `@default` runs.
- If no decorators exist in the file, falls back to `handle(payload, ctx)` (simple style).

## HookContext

Every handler receives a `ctx` object with parsed payload accessors:

| Property | Description |
|----------|-------------|
| `ctx.event` | Event name (`"PreToolUse"`, `"PostToolUse"`, etc.) |
| `ctx.tool_name` | Tool being called (`"Bash"`, `"Write"`, etc.) |
| `ctx.tool_input` | Full tool input dict |
| `ctx.tool_response` | Tool response (PostToolUse only) |
| `ctx.session_id` | Session ID |
| `ctx.cwd` | Working directory |
| `ctx.target` | Target assistant (`"claude"` or `"copilot"`) |
| `ctx.is_claude` | `True` when triggered by Claude Code |
| `ctx.is_copilot` | `True` when triggered by GitHub Copilot |
| `ctx.payload` | Raw payload dict |

### Tool shortcuts

| Property | Description |
|----------|-------------|
| `ctx.command` | Bash: the command string |
| `ctx.file_path` | Read/Write/Edit: the file path |
| `ctx.content` | Write: the file content |

## Response Builders

### PreToolUse / PermissionRequest

```python
ctx.deny("reason")       # Block the tool call
ctx.allow()              # Explicitly approve
ctx.ask("reason")        # Ask user for confirmation
ctx.modify(command="safer cmd")  # Rewrite input + auto-approve
```

### PostToolUse

```python
ctx.block("reason")      # Flag the tool output
```

### General (any event)

```python
ctx.context("extra info")       # Inject context visible to the model
ctx.system_message("text")      # Inject a system message
ctx.combine(                    # Merge multiple responses
    ctx.allow(),
    ctx.system_message("Approved with note")
)
```

### Logging

```python
ctx.log("message")  # Prints to stderr: [phaicaid] message
```

## Simple Style

The `handle(payload, ctx)` style works for hooks that don't need tool scoping:

```python
def handle(payload, ctx):
    ctx.log("hello")
    return None
```

If a file has both decorators and `handle()`, decorators take precedence.

## Architecture

```
Claude Code / Copilot
  |  stdin: hook payload JSON
  v
.phaicaid/bin/phaicaid-run  (bash + socat, ~1ms)
  |  unix socket
  v
Python daemon (run_daemon.py, long-lived)
  |  imports cached, hot-reloaded via inotify
  v
.phaicaid/hooks/*.py  (your code)
```

The daemon starts automatically on first hook invocation and stays running. Hook modules are cached in memory and reloaded only when the file changes on disk — edits take effect instantly without restarting anything.

The bash+socat runner avoids Node.js startup overhead on the hot path. For environments without socat, `npx phaicaid run --event <event>` works as a fallback.

## Benchmarks

Average latency per hook invocation (N=100):

| Scenario | phaicaid (daemon) | Direct Python (no daemon) | Speedup |
|----------|:-----------------:|:-------------------------:|:-------:|
| Trivial hook (`return None`) | **13ms** | 23ms | 1.8x |
| Heavy hook (16 stdlib imports + sha256) | **12ms** | 68ms | 5.7x |

The daemon amortizes Python startup and import costs. phaicaid stays flat at ~12ms regardless of how heavy your imports are, while direct Python pays the full startup+import cost every time.

## CLI Reference

| Command | Description |
|---------|-------------|
| `npx phaicaid init --target claude\|copilot` | Set up runtime + hooks config |
| `npx phaicaid add <event> [--simple]` | Scaffold a hook file |
| `npx phaicaid add all` | Scaffold all hook events at once |
| `npx phaicaid doctor` | Check runtime health |
| `npx phaicaid snippet --target claude\|copilot` | Print hooks config JSON |
| `npx phaicaid run --event <event> [--target claude\|copilot]` | Run a hook (Node.js fallback runner) |
| `npx phaicaid stop` | Stop the running daemon |
| `npx phaicaid restart` | Restart the daemon |
| `npx phaicaid clean` | Stop daemon and remove `.phaicaid/` runtime dir |

## File Layout

```
.phaicaid/
├── bin/phaicaid-run        # bash+socat runner (copied at init)
├── hooks/                  # your Python hook files
│   ├── pre_tool_use.py
│   ├── post_tool_use.py
│   ├── session_start.py
│   └── ...                 # one file per event
├── pydaemon/
│   ├── run_daemon.py       # daemon entry point
│   └── phaicaid/           # SDK package
│       ├── __init__.py
│       ├── context.py      # HookContext + response builders
│       ├── decorators.py   # @tool, @default
│       └── _registry.py    # handler dispatch
├── run/                    # runtime state (socket, pid, logs)
└── venv/                   # Python virtual environment
```
