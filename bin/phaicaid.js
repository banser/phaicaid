#!/usr/bin/env node
import { Command } from "commander";
import fs from "node:fs";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";

const program = new Command();

function root() { return process.cwd(); }
function rtDir(r) { return path.join(r, ".phaicaid"); }
function ensureDir(p) { fs.mkdirSync(p, { recursive: true }); }

function pythonPath(r) {
  const venvPy = process.platform === "win32"
    ? path.join(rtDir(r), "venv", "Scripts", "python.exe")
    : path.join(rtDir(r), "venv", "bin", "python");
  if (fs.existsSync(venvPy)) return venvPy;
  return process.env.PHAICAID_PYTHON || (process.platform === "win32" ? "python" : "python3");
}

function daemonEntry(r) {
  return path.join(rtDir(r), "pydaemon", "run_daemon.py");
}

function copyDir(src, dst) {
  ensureDir(dst);
  for (const ent of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, ent.name);
    const d = path.join(dst, ent.name);
    if (ent.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function ensureVenv(r) {
  const venv = path.join(rtDir(r), "venv");
  if (fs.existsSync(venv)) return;
  ensureDir(rtDir(r));
  const py = process.env.PHAICAID_PYTHON || (process.platform === "win32" ? "python" : "python3");
  console.error("[phaicaid] creating venv...");
  const res = spawnSync(py, ["-m", "venv", venv], { stdio: "inherit", cwd: r });
  if (res.status !== 0) process.exit(res.status ?? 1);
  const vpy = pythonPath(r);
  spawnSync(vpy, ["-m", "pip", "install", "-U", "pip"], { stdio: "inherit", cwd: r });
}

function copyTemplates(r) {
  const pkgDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
  const templateDir = path.join(pkgDir, "templates");
  const dst = rtDir(r);
  ensureDir(dst);
  copyDir(path.join(templateDir, "pydaemon"), path.join(dst, "pydaemon"));
  ensureDir(path.join(dst, "hooks"));
  const examples = {
    "pre_tool_use.py": `from phaicaid import tool, default

@tool("Bash")
def guard_bash(ctx):
    """Example: block dangerous shell commands."""
    if "rm -rf" in ctx.command:
        return ctx.deny("Blocked dangerous command")

@default
def log_all(ctx):
    ctx.log(f"pre_tool_use: {ctx.tool_name}")
`,
    "post_tool_use.py": `from phaicaid import tool, default

@default
def log_all(ctx):
    ctx.log(f"post_tool_use: {ctx.tool_name}")
`,
    "session_start.py": `def handle(payload, ctx):
    ctx.log("session_start")
    return None
`
  };
  for (const [fn, content] of Object.entries(examples)) {
    const p = path.join(dst, "hooks", fn);
    if (!fs.existsSync(p)) fs.writeFileSync(p, content, "utf8");
  }
  ensureDir(path.join(dst, "run"));
  // Install the fast bash+socat runner into .phaicaid/bin/
  const binDir = path.join(dst, "bin");
  ensureDir(binDir);
  fs.copyFileSync(path.join(pkgDir, "bin", "phaicaid-run-bash"), path.join(binDir, "phaicaid-run"));
  fs.chmodSync(path.join(binDir, "phaicaid-run"), 0o755);
}

function runCmd(event, target) {
  // Use the fast bash+socat client for the hot path.
  // The script is copied into .phaicaid/ at init time so it's always available.
  return `.phaicaid/bin/phaicaid-run --event ${event} --target ${target}`;
}

// Events that support matcher (tool name, agent type, etc.) in Claude Code.
const CLAUDE_MATCHER_EVENTS = new Set([
  "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
  "SubagentStart", "SubagentStop", "Notification", "ConfigChange",
  "PreCompact", "SessionStart", "SessionEnd",
]);

function claudeHookEntry(event) {
  const hook = { type: "command", command: runCmd(event, "claude") };
  if (CLAUDE_MATCHER_EVENTS.has(event)) {
    return [{ matcher: ".*", hooks: [hook] }];
  }
  return [{ hooks: [hook] }];
}

function hooksJson(target) {
  if (target === "claude") {
    const hooks = {};
    for (const ev of [
      "SessionStart", "SessionEnd",
      "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
      "UserPromptSubmit", "Notification",
      "SubagentStart", "SubagentStop",
      "Stop", "TeammateIdle", "TaskCompleted",
      "ConfigChange", "PreCompact",
      // WorktreeCreate/WorktreeRemove omitted — they replace default git
      // behavior and should only be registered intentionally.
    ]) {
      hooks[ev] = claudeHookEntry(ev);
    }
    return JSON.stringify({ hooks }, null, 2);
  }
  if (target === "copilot") {
    return JSON.stringify({
      sessionStart: [{ command: runCmd("sessionStart", "copilot") }],
      sessionEnd: [{ command: runCmd("sessionEnd", "copilot") }],
      userPromptSubmitted: [{ command: runCmd("userPromptSubmitted", "copilot") }],
      preToolUse: [{ command: runCmd("preToolUse", "copilot") }],
      postToolUse: [{ command: runCmd("postToolUse", "copilot") }],
      errorOccurred: [{ command: runCmd("errorOccurred", "copilot") }]
    }, null, 2);
  }
  throw new Error("target must be claude|copilot");
}

function startDaemon(r) {
  const py = pythonPath(r);
  const entry = daemonEntry(r);
  const logPath = path.join(rtDir(r), "run", "daemon.log");
  const out = fs.openSync(logPath, "a");
  const err = fs.openSync(logPath, "a");
  const child = spawn(py, [entry, "--runtime", rtDir(r)], { cwd: r, detached: true, stdio: ["ignore", out, err] });
  child.unref();
}

function sleep(ms){ return new Promise(res => setTimeout(res, ms)); }

async function ensureDaemon(r) {
  const runDir = path.join(rtDir(r), "run");
  const sock = path.join(runDir, "phaicaid.sock");
  const portFile = path.join(runDir, "port.txt");

  async function pingUnix() {
    const net = (await import("node:net")).default;
    return new Promise((resolve) => {
      const c = net.createConnection(sock, () => { c.end(); resolve(true); });
      c.on("error", () => resolve(false));
    });
  }
  async function pingTcp(port) {
    const net = (await import("node:net")).default;
    return new Promise((resolve) => {
      const c = net.createConnection({host:"127.0.0.1", port}, () => { c.end(); resolve(true); });
      c.on("error", () => resolve(false));
    });
  }

  if (process.platform !== "win32") {
    if (fs.existsSync(sock) && await pingUnix()) return;
    startDaemon(r);
    for (let i=0;i<40;i++){ if (fs.existsSync(sock) && await pingUnix()) return; await sleep(50); }
    console.error("[phaicaid] warning: daemon did not start within 2s — check .phaicaid/run/daemon.log");
    return;
  } else {
    if (fs.existsSync(portFile)) {
      const p = parseInt(fs.readFileSync(portFile,"utf8").trim(),10);
      if (p>0 && await pingTcp(p)) return;
    }
    startDaemon(r);
    for (let i=0;i<40;i++){
      if (fs.existsSync(portFile)) {
        const p = parseInt(fs.readFileSync(portFile,"utf8").trim(),10);
        if (p>0 && await pingTcp(p)) return;
      }
      await sleep(50);
    }
    console.error("[phaicaid] warning: daemon did not start within 2s — check .phaicaid/run/daemon.log");
  }
}

async function rpc(r, msg) {
  const runDir = path.join(rtDir(r), "run");
  const sock = path.join(runDir, "phaicaid.sock");
  const portFile = path.join(runDir, "port.txt");
  const net = (await import("node:net")).default;

  if (process.platform !== "win32") {
    return new Promise((resolve, reject) => {
      const c = net.createConnection(sock);
      let buf = "";
      c.setEncoding("utf8");
      c.on("connect", () => c.write(msg + "\n"));
      c.on("data", (ch) => { buf += ch; if (buf.includes("\n")) { c.end(); resolve(buf.split("\n")[0]); }});
      c.on("error", reject);
    });
  } else {
    const port = parseInt(fs.readFileSync(portFile,"utf8").trim(),10);
    return new Promise((resolve, reject) => {
      const c = net.createConnection({host:"127.0.0.1", port});
      let buf = "";
      c.setEncoding("utf8");
      c.on("connect", () => c.write(msg + "\n"));
      c.on("data", (ch) => { buf += ch; if (buf.includes("\n")) { c.end(); resolve(buf.split("\n")[0]); }});
      c.on("error", reject);
    });
  }
}

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => data += c);
    process.stdin.on("end", () => resolve(data));
  });
}

program.name("phaicaid").version("0.1.0");

program.command("init")
  .requiredOption("--target <target>", "claude|copilot")
  .action((opts) => {
    const r = root();
    ensureVenv(r);
    copyTemplates(r);
    if (opts.target === "claude") {
      ensureDir(path.join(r, ".claude"));
      fs.writeFileSync(path.join(r, ".claude", "hooks.json"), hooksJson("claude"), "utf8");
      console.error("[phaicaid] wrote .claude/hooks.json");
    } else if (opts.target === "copilot") {
      fs.writeFileSync(path.join(r, "hooks.json"), hooksJson("copilot"), "utf8");
      console.error("[phaicaid] wrote hooks.json");
    } else {
      throw new Error("target must be claude|copilot");
    }
    console.error("[phaicaid] python hooks live in .phaicaid/hooks/");
  });

program.command("snippet")
  .requiredOption("--target <target>", "claude|copilot")
  .action((opts) => console.log(hooksJson(opts.target)));

// ---------------------------------------------------------------------------
// phaicaid add — scaffold a hook file
// ---------------------------------------------------------------------------
function toSnake(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z])([A-Z][a-z])/g, "$1_$2")
    .toLowerCase();
}

// Events where @tool() decorator (tool-name scoping) makes sense.
const TOOL_SCOPED_EVENTS = new Set([
  "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
]);

// All known events across both targets (PascalCase canonical names).
const ALL_EVENTS = [
  // Claude Code
  "SessionStart", "SessionEnd",
  "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
  "UserPromptSubmit", "Notification",
  "SubagentStart", "SubagentStop",
  "Stop", "TeammateIdle", "TaskCompleted",
  "ConfigChange", "PreCompact",
  "WorktreeCreate", "WorktreeRemove",
];

function hookTemplate(event, simple) {
  const snake = toSnake(event);
  if (simple || !TOOL_SCOPED_EVENTS.has(event)) {
    return `def handle(payload, ctx):\n    ctx.log("${snake}")\n    return None\n`;
  }
  if (event === "PreToolUse") {
    return `from phaicaid import tool, default

@tool("Bash")
def guard_bash(ctx):
    # Example: block dangerous commands
    if "rm -rf" in ctx.command:
        return ctx.deny("Blocked dangerous command")

@tool("Write", "Edit")
def protect_env(ctx):
    if ctx.file_path.endswith(".env"):
        return ctx.deny("Cannot modify .env files")

@default
def log_all(ctx):
    ctx.log(f"pre_tool_use: {ctx.tool_name}")
`;
  }
  if (event === "PermissionRequest") {
    return `from phaicaid import tool, default

@default
def log_all(ctx):
    ctx.log(f"permission_request: {ctx.tool_name}")
`;
  }
  // PostToolUse, PostToolUseFailure
  return `from phaicaid import tool, default

@default
def log_all(ctx):
    ctx.log(f"${snake}: {ctx.tool_name}")
`;
}

program.command("add")
  .argument("<event>", 'hook event name (e.g. PreToolUse, PostToolUse, SessionStart) or "all"')
  .option("--simple", "generate simple handle(payload, ctx) template")
  .action((event, opts) => {
    const r = root();
    const hooksDir = path.join(rtDir(r), "hooks");
    ensureDir(hooksDir);

    const events = event === "all" ? ALL_EVENTS : [event];
    let created = 0;

    for (const ev of events) {
      const fileName = toSnake(ev) + ".py";
      const filePath = path.join(hooksDir, fileName);
      if (fs.existsSync(filePath)) {
        if (event !== "all") {
          console.error(`[phaicaid] ${filePath} already exists — refusing to overwrite`);
          process.exit(1);
        }
        console.error(`[phaicaid] skipped ${fileName} (already exists)`);
        continue;
      }
      const content = hookTemplate(ev, !!opts.simple);
      fs.writeFileSync(filePath, content, "utf8");
      console.error(`[phaicaid] created ${path.relative(r, filePath)}`);
      created++;
    }

    if (event === "all") {
      console.error(`[phaicaid] created ${created} hook file(s)`);
    }
  });

program.command("doctor")
  .action(async () => {
    const r = root();
    console.log("repo:", r);
    console.log("runtime:", rtDir(r), fs.existsSync(rtDir(r)) ? "OK" : "MISSING");
    await ensureDaemon(r);
    console.log("daemon: OK (started/probed)");
  });

program.command("run")
  .requiredOption("--event <event>", "event name")
  .option("--target <target>", "target assistant (claude|copilot)", "claude")
  .action(async (opts) => {
    const r = root();
    const stdin = await readStdin();
    await ensureDaemon(r);
    const payload = stdin.trim() ? JSON.parse(stdin) : {};
    const msg = JSON.stringify({ op: "hook", data: { __event: opts.event, __payload: payload, __target: opts.target } });

    try {
      const resp = await rpc(r, msg);
      // The daemon returns {"ok":true,"result":{...}} envelope.
      // Extract .result so Claude Code / Copilot gets bare hook JSON.
      try {
        const parsed = JSON.parse(resp);
        if (parsed.ok && parsed.result != null) {
          process.stdout.write(JSON.stringify(parsed.result) + "\n");
        } else if (!parsed.ok) {
          console.error("[phaicaid] hook error:", parsed.error);
          process.exit(1);
        }
        // ok=true with null result → no output (hook returned None)
      } catch {
        // Not JSON or parse error — pass through as-is.
        if (resp.trim()) process.stdout.write(resp + "\n");
      }
    } catch (e) {
      console.error("[phaicaid] rpc failed:", e?.message || e);
      process.exit(1);
    }
  });

// ---------------------------------------------------------------------------
// phaicaid stop / restart / clean
// ---------------------------------------------------------------------------
function readPid(r) {
  const pidFile = path.join(rtDir(r), "run", "daemon.pid");
  if (!fs.existsSync(pidFile)) return null;
  const raw = fs.readFileSync(pidFile, "utf8").trim();
  const pid = parseInt(raw, 10);
  return pid > 0 ? pid : null;
}

async function stopDaemon(r) {
  const pid = readPid(r);
  if (pid == null) {
    console.error("[phaicaid] no running daemon found");
    return;
  }
  try {
    process.kill(pid, "SIGTERM");
  } catch (e) {
    if (e.code === "ESRCH") {
      // Process already gone — clean up stale PID file.
      const pidFile = path.join(rtDir(r), "run", "daemon.pid");
      try { fs.unlinkSync(pidFile); } catch {}
      console.error("[phaicaid] stale pid file removed (process already gone)");
      return;
    }
    throw e;
  }
  // Wait up to 2s for the daemon to exit.
  for (let i = 0; i < 40; i++) {
    try { process.kill(pid, 0); } catch { console.error("[phaicaid] daemon stopped"); return; }
    await sleep(50);
  }
  console.error("[phaicaid] warning: daemon (pid " + pid + ") did not exit within 2s");
}

program.command("stop")
  .description("Stop the running daemon")
  .action(async () => { await stopDaemon(root()); });

program.command("restart")
  .description("Restart the daemon")
  .action(async () => {
    const r = root();
    await stopDaemon(r);
    await sleep(200);
    await ensureDaemon(r);
    console.error("[phaicaid] daemon restarted");
  });

program.command("clean")
  .description("Stop daemon and remove .phaicaid runtime directory")
  .action(async () => {
    const r = root();
    await stopDaemon(r);
    fs.rmSync(rtDir(r), { recursive: true, force: true });
    console.error("[phaicaid] cleaned " + rtDir(r));
  });

program.parse(process.argv);
