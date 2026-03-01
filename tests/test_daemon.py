"""Tests for run_daemon — dispatch, handle_req, to_snake, module caching."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

# run_daemon is a script, not a package — import it by adding to path.
_pydaemon_dir = str(Path(__file__).resolve().parent.parent / "templates" / "pydaemon")
if _pydaemon_dir not in sys.path:
    sys.path.insert(0, _pydaemon_dir)

import run_daemon  # noqa: E402


class TestToSnake:
    def test_pascal_case(self) -> None:
        assert run_daemon.to_snake("PreToolUse") == "pre_tool_use"

    def test_camel_case(self) -> None:
        assert run_daemon.to_snake("sessionStart") == "session_start"

    def test_single_word(self) -> None:
        assert run_daemon.to_snake("Stop") == "stop"

    def test_already_snake(self) -> None:
        assert run_daemon.to_snake("pre_tool_use") == "pre_tool_use"

    def test_consecutive_caps(self) -> None:
        assert run_daemon.to_snake("PostToolUseFailure") == "post_tool_use_failure"

    def test_empty_string(self) -> None:
        assert run_daemon.to_snake("") == ""


class TestDispatch:
    def test_returns_none_when_no_hook_file(self, tmp_runtime: Path) -> None:
        result = run_daemon.dispatch("NonExistent", {}, tmp_runtime)
        assert result is None

    def test_simple_style_handle(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "pre_tool_use.py"
        hook_file.write_text(textwrap.dedent("""\
            def handle(payload, ctx):
                return {"handled": True, "tool": payload.get("toolName", "")}
        """))

        # Clear module cache to ensure fresh load.
        run_daemon.invalidate_module(hook_file)

        result = run_daemon.dispatch(
            "PreToolUse", {"toolName": "Bash"}, tmp_runtime,
        )
        assert result == {"handled": True, "tool": "Bash"}

    def test_decorator_style_dispatch(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "pre_tool_use.py"
        hook_file.write_text(textwrap.dedent("""\
            import sys, os
            # Add pydaemon to path so we can import phaicaid
            _dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            _pydaemon = os.path.join(_dir, "pydaemon")
            if _pydaemon not in sys.path:
                sys.path.insert(0, _pydaemon)

            from phaicaid import tool, default

            @tool("Bash")
            def guard(ctx):
                return {"decision": "deny", "reason": "blocked"}

            @default
            def fallback(ctx):
                return {"decision": "allow"}
        """))

        # We need the pydaemon dir next to hooks for the import to work.
        # Copy the SDK package into our temp runtime.
        import shutil
        sdk_src = Path(__file__).resolve().parent.parent / "templates" / "pydaemon" / "phaicaid"
        sdk_dst = tmp_runtime / "pydaemon" / "phaicaid"
        if not sdk_dst.exists():
            shutil.copytree(str(sdk_src), str(sdk_dst))

        run_daemon.invalidate_module(hook_file)

        # Bash should hit @tool("Bash")
        result = run_daemon.dispatch(
            "PreToolUse", {"toolName": "Bash"}, tmp_runtime,
        )
        assert result == {"decision": "deny", "reason": "blocked"}

        # Write should fall to @default
        result = run_daemon.dispatch(
            "PreToolUse", {"toolName": "Write"}, tmp_runtime,
        )
        assert result == {"decision": "allow"}

    def test_handle_missing_returns_none(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "session_start.py"
        hook_file.write_text("x = 42\n")  # No handle(), no decorators.
        run_daemon.invalidate_module(hook_file)

        result = run_daemon.dispatch("SessionStart", {}, tmp_runtime)
        assert result is None


class TestModuleCache:
    def test_get_module_caches(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "test_cache.py"
        hook_file.write_text("VALUE = 1\n")
        run_daemon.invalidate_module(hook_file)

        mod1 = run_daemon.get_module(hook_file)
        mod2 = run_daemon.get_module(hook_file)
        assert mod1 is mod2

    def test_invalidate_forces_reload(self, tmp_runtime: Path) -> None:
        # Use a unique filename to avoid any cross-test contamination.
        import uuid

        name = f"reload_{uuid.uuid4().hex[:8]}"
        hook_file = tmp_runtime / "hooks" / f"{name}.py"
        hook_file.write_text("VALUE = 1\n")

        mod1 = run_daemon.get_module(hook_file)
        assert mod1.VALUE == 1  # type: ignore[attr-defined]

        run_daemon.invalidate_module(hook_file)
        hook_file.write_text("VALUE = 2\n")
        # Clear sys.modules and bytecache to ensure a truly fresh import.
        sys.modules.pop(name, None)
        pyc = hook_file.parent / "__pycache__"
        if pyc.exists():
            import shutil

            shutil.rmtree(pyc)

        mod2 = run_daemon.get_module(hook_file)
        assert mod2.VALUE == 2  # type: ignore[attr-defined]
        assert mod1 is not mod2


class TestHandleReq:
    def test_ping(self, tmp_runtime: Path) -> None:
        resp = run_daemon.handle_req('{"op":"ping"}', tmp_runtime)
        assert json.loads(resp) == {"ok": True}

    def test_bad_json(self, tmp_runtime: Path) -> None:
        resp = run_daemon.handle_req("not json", tmp_runtime)
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error"] == "bad_json"

    def test_unknown_op(self, tmp_runtime: Path) -> None:
        resp = run_daemon.handle_req('{"op":"unknown"}', tmp_runtime)
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert parsed["error"] == "unknown_op"

    def test_hook_envelope_mode(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "session_start.py"
        hook_file.write_text("def handle(payload, ctx): return {'test': True}\n")
        run_daemon.invalidate_module(hook_file)

        req = json.dumps({
            "op": "hook",
            "data": {"__event": "SessionStart", "__payload": {}},
        })
        resp = run_daemon.handle_req(req, tmp_runtime)
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert parsed["result"] == {"test": True}

    def test_hook_raw_mode(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "session_start.py"
        hook_file.write_text(
            "def handle(payload, ctx): return {'decision': 'allow'}\n",
        )
        run_daemon.invalidate_module(hook_file)

        req = json.dumps({
            "op": "hook",
            "raw": True,
            "data": {"__event": "SessionStart", "__payload": {}},
        })
        resp = run_daemon.handle_req(req, tmp_runtime)
        parsed = json.loads(resp)
        assert parsed == {"decision": "allow"}

    def test_hook_raw_mode_none_result(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "session_start.py"
        hook_file.write_text("def handle(payload, ctx): return None\n")
        run_daemon.invalidate_module(hook_file)

        req = json.dumps({
            "op": "hook",
            "raw": True,
            "data": {"__event": "SessionStart", "__payload": {}},
        })
        resp = run_daemon.handle_req(req, tmp_runtime)
        assert resp == ""

    def test_hook_no_file_returns_null(self, tmp_runtime: Path) -> None:
        req = json.dumps({
            "op": "hook",
            "data": {"__event": "NonExistent", "__payload": {}},
        })
        resp = run_daemon.handle_req(req, tmp_runtime)
        parsed = json.loads(resp)
        assert parsed["ok"] is True
        assert parsed["result"] is None

    def test_hook_error_envelope(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "session_start.py"
        hook_file.write_text("def handle(payload, ctx): raise ValueError('boom')\n")
        run_daemon.invalidate_module(hook_file)

        req = json.dumps({
            "op": "hook",
            "data": {"__event": "SessionStart", "__payload": {}},
        })
        resp = run_daemon.handle_req(req, tmp_runtime)
        parsed = json.loads(resp)
        assert parsed["ok"] is False
        assert "boom" in parsed["error"]

    def test_hook_error_raw(self, tmp_runtime: Path) -> None:
        hook_file = tmp_runtime / "hooks" / "session_start.py"
        hook_file.write_text("def handle(payload, ctx): raise ValueError('boom')\n")
        run_daemon.invalidate_module(hook_file)

        req = json.dumps({
            "op": "hook",
            "raw": True,
            "data": {"__event": "SessionStart", "__payload": {}},
        })
        resp = run_daemon.handle_req(req, tmp_runtime)
        parsed = json.loads(resp)
        assert "boom" in parsed["error"]
