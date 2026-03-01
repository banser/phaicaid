#!/usr/bin/env python3
"""phaicaid daemon — long-lived Python process that serves hook handlers.

Listens on a Unix domain socket (or TCP on Windows) and dispatches incoming
hook events to the appropriate Python handler module in ``<runtime>/hooks/``.
Modules are cached in memory and hot-reloaded via inotify (Linux) or polling.
"""

from __future__ import annotations

import argparse
import atexit
import importlib.util
import json
import os
import re
import socket
import sys
import threading
import time
import traceback
import types
from pathlib import Path
from typing import Any

# Make the phaicaid SDK importable from user hooks.
# The SDK lives alongside this file at <runtime>/pydaemon/phaicaid/
_pydaemon_dir = str(Path(__file__).resolve().parent)
if _pydaemon_dir not in sys.path:
    sys.path.insert(0, _pydaemon_dir)

from phaicaid._registry import dispatch_decorated, has_decorators  # noqa: E402
from phaicaid.context import HookContext  # noqa: E402


def _eprint(*args: object, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)


def to_snake(name: str) -> str:
    """Convert PascalCase or camelCase to snake_case.

    Examples:
        >>> to_snake("PreToolUse")
        'pre_tool_use'
        >>> to_snake("sessionStart")
        'session_start'
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# ---------------------------------------------------------------------------
# Module cache — loaded modules stay in memory until their file changes.
# ---------------------------------------------------------------------------
_module_cache: dict[Path, types.ModuleType] = {}
_module_mtime: dict[Path, int] = {}
_cache_lock = threading.Lock()


def _load_fresh(file_path: Path) -> types.ModuleType:
    """Import a Python file as a fresh module (not from ``sys.modules``)."""
    spec = importlib.util.spec_from_file_location(file_path.stem, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def get_module(file_path: Path) -> types.ModuleType:
    """Return a cached module, reloading only if the file changed on disk."""
    with _cache_lock:
        cached = _module_cache.get(file_path)
        if cached is not None:
            # Check whether the file has been modified since we cached it.
            try:
                current_mtime = file_path.stat().st_mtime_ns
            except OSError:
                # File deleted — return stale cache gracefully.
                return cached
            if current_mtime == _module_mtime.get(file_path):
                return cached
            # Mtime changed — evict and reload below.
            _module_cache.pop(file_path, None)
            _module_mtime.pop(file_path, None)
        mod = _load_fresh(file_path)
        _module_cache[file_path] = mod
        _module_mtime[file_path] = file_path.stat().st_mtime_ns
        return mod


def invalidate_module(file_path: Path) -> None:
    """Remove a module from the cache so the next request reloads it."""
    with _cache_lock:
        _module_cache.pop(file_path, None)
        _module_mtime.pop(file_path, None)


# ---------------------------------------------------------------------------
# File watcher — inotify on Linux, polling fallback elsewhere.
# ---------------------------------------------------------------------------
def _watch_inotify(hooks_dir: Path) -> None:
    """Use Linux inotify to watch for writes/moves/deletes — no polling."""
    import ctypes
    import ctypes.util
    import struct

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.inotify_init.restype = ctypes.c_int
    libc.inotify_add_watch.restype = ctypes.c_int
    libc.inotify_add_watch.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]

    IN_MODIFY = 0x00000002
    IN_MOVED_TO = 0x00000080
    IN_CREATE = 0x00000100
    IN_DELETE = 0x00000200
    MASK = IN_MODIFY | IN_CREATE | IN_DELETE | IN_MOVED_TO

    fd = libc.inotify_init()
    if fd < 0:
        raise OSError("inotify_init failed")
    wd = libc.inotify_add_watch(fd, str(hooks_dir).encode(), MASK)
    if wd < 0:
        os.close(fd)
        raise OSError("inotify_add_watch failed")

    _eprint(f"[phaicaid] watching {hooks_dir} via inotify")
    event_hdr_size = struct.calcsize("iIII")

    try:
        while True:
            n = os.read(fd, 4096)
            if not n:
                continue
            offset = 0
            while offset < len(n):
                _wd_ev, _mask, _cookie, name_len = struct.unpack_from(
                    "iIII",
                    n,
                    offset,
                )
                name_bytes = n[offset + event_hdr_size : offset + event_hdr_size + name_len]
                name = name_bytes.rstrip(b"\x00").decode()
                offset += event_hdr_size + name_len
                if name.endswith(".py"):
                    invalidate_module(hooks_dir / name)
                    _eprint(f"[phaicaid] reloaded {name}")
    finally:
        os.close(fd)


def _watch_poll(hooks_dir: Path) -> None:
    """Fallback: poll mtime every 500ms."""
    _eprint(f"[phaicaid] watching {hooks_dir} via polling")
    mt: dict[Path, int] = {}
    while True:
        try:
            for p in hooks_dir.glob("*.py"):
                t = p.stat().st_mtime_ns
                if p not in mt:
                    mt[p] = t
                elif mt[p] != t:
                    mt[p] = t
                    invalidate_module(p)
                    _eprint(f"[phaicaid] reloaded {p.name}")
            # Detect deletions.
            gone = [p for p in mt if not p.exists()]
            for p in gone:
                del mt[p]
                invalidate_module(p)
        except OSError:
            pass  # Filesystem race (file deleted mid-scan); retry next cycle.
        time.sleep(0.5)


def start_watcher(hooks_dir: Path) -> None:
    """Start file watcher in a daemon thread. inotify if possible, else poll."""

    def _run() -> None:
        if sys.platform == "linux":
            try:
                _watch_inotify(hooks_dir)
                return
            except OSError as exc:
                _eprint(f"[phaicaid] inotify unavailable ({exc}), falling back to poll")
        _watch_poll(hooks_dir)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Dispatch & request handling
# ---------------------------------------------------------------------------
def dispatch(
    event: str,
    payload: dict[str, Any],
    runtime_dir: Path,
    target: str = "",
) -> dict[str, Any] | None:
    """Load the hook module for *event* and call the appropriate handler.

    Decorator-style dispatch (``@tool``/``@default``) takes priority.
    Falls back to ``handle(payload, ctx)`` if no decorators are found.

    Returns ``None`` if no hook file exists or the handler returns nothing.
    """
    hooks_dir = runtime_dir / "hooks"
    fn = hooks_dir / f"{to_snake(event)}.py"
    if not fn.exists():
        return None
    mod = get_module(fn)
    ctx = HookContext(event, payload, runtime_dir, target=target)

    # Decorator-style dispatch takes priority.
    if has_decorators(mod):
        return dispatch_decorated(mod, ctx.tool_name, ctx)

    # Simple style fallback: handle(payload, ctx).
    handler = getattr(mod, "handle", None)
    if handler is None:
        return None
    return handler(payload, ctx)


def handle_req(line: str, runtime_dir: Path) -> str:
    """Parse a JSON request line and return a JSON response string.

    Supported operations:
        - ``{"op": "ping"}`` — health check.
        - ``{"op": "hook", "data": {...}}`` — dispatch a hook event.
        - ``{"op": "hook", "raw": true, ...}`` — return bare result JSON.
    """
    try:
        req = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"ok": False, "error": "bad_json"})

    if req.get("op") == "ping":
        return json.dumps({"ok": True})

    if req.get("op") == "hook":
        data = req.get("data") or {}
        event = data.get("__event") or ""
        payload = data.get("__payload") or {}
        target: str = data.get("__target") or ""
        raw: bool = req.get("raw", False)
        try:
            res = dispatch(str(event), payload, runtime_dir, target=target)
            if raw:
                # Return bare result JSON — Claude Code expects this shape.
                return json.dumps(res) if res is not None else ""
            return json.dumps({"ok": True, "result": res})
        except Exception as exc:
            if raw:
                return json.dumps({"error": str(exc)})
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "trace": traceback.format_exc(limit=8),
                }
            )

    return json.dumps({"ok": False, "error": "unknown_op"})


# ---------------------------------------------------------------------------
# Socket servers
# ---------------------------------------------------------------------------
def _handle_conn(conn: socket.socket, runtime_dir: Path) -> None:
    """Read one newline-delimited request and send back the response."""
    with conn:
        data = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                line = data.split(b"\n", 1)[0]
                resp = handle_req(line.decode("utf-8"), runtime_dir)
                conn.sendall((resp + "\n").encode("utf-8"))
                break


def serve_unix(sock_path: Path, runtime_dir: Path) -> None:
    """Listen on a Unix domain socket and serve hook requests."""
    if sock_path.exists():
        sock_path.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    srv.listen(64)
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(
                target=_handle_conn,
                args=(conn, runtime_dir),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        if sock_path.exists():
            sock_path.unlink()


def serve_tcp(port_file: Path, runtime_dir: Path) -> None:
    """Listen on a TCP port (Windows) and serve hook requests."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(64)
    port = srv.getsockname()[1]
    port_file.write_text(str(port), encoding="utf-8")
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(
                target=_handle_conn,
                args=(conn, runtime_dir),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        import contextlib

        with contextlib.suppress(OSError):
            port_file.unlink()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Entry point: parse args, start watcher, and serve."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True)
    args = ap.parse_args()
    runtime_dir = Path(args.runtime).resolve()
    hooks_dir = runtime_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    run_dir = runtime_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Write PID file so the CLI can signal the daemon.
    pid_file = run_dir / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")

    def _remove_pid() -> None:
        import contextlib

        with contextlib.suppress(OSError):
            pid_file.unlink()

    atexit.register(_remove_pid)

    start_watcher(hooks_dir)

    if os.name != "nt":
        sock = run_dir / "phaicaid.sock"
        _eprint(f"[phaicaid] listening unix {sock}")
        serve_unix(sock, runtime_dir)
    else:
        port_file = run_dir / "port.txt"
        _eprint(f"[phaicaid] listening tcp (port file {port_file})")
        serve_tcp(port_file, runtime_dir)


if __name__ == "__main__":
    main()
