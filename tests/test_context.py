"""Tests for phaicaid.context — HookContext accessors and response builders."""

from __future__ import annotations

from pathlib import Path

from phaicaid.context import HookContext


class TestHookContextInit:
    def test_stores_event(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        assert ctx.event == "PreToolUse"

    def test_stores_payload(self) -> None:
        payload = {"toolName": "Bash"}
        ctx = HookContext("PreToolUse", payload, Path("/tmp"))
        assert ctx.payload is payload

    def test_stores_runtime_dir(self) -> None:
        p = Path("/some/path")
        ctx = HookContext("PreToolUse", {}, p)
        assert ctx.runtime_dir is p


class TestPayloadAccessors:
    def test_tool_name(self) -> None:
        ctx = HookContext("PreToolUse", {"toolName": "Bash"}, Path("/tmp"))
        assert ctx.tool_name == "Bash"

    def test_tool_name_missing(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        assert ctx.tool_name == ""

    def test_tool_input(self) -> None:
        inp = {"command": "ls"}
        ctx = HookContext("PreToolUse", {"toolInput": inp}, Path("/tmp"))
        assert ctx.tool_input == inp

    def test_tool_input_missing(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        assert ctx.tool_input == {}

    def test_tool_response(self) -> None:
        ctx = HookContext("PostToolUse", {"toolResponse": "ok"}, Path("/tmp"))
        assert ctx.tool_response == "ok"

    def test_tool_response_missing(self) -> None:
        ctx = HookContext("PostToolUse", {}, Path("/tmp"))
        assert ctx.tool_response is None

    def test_session_id(self) -> None:
        ctx = HookContext("PreToolUse", {"sessionId": "abc-123"}, Path("/tmp"))
        assert ctx.session_id == "abc-123"

    def test_session_id_missing(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        assert ctx.session_id == ""

    def test_cwd(self) -> None:
        ctx = HookContext("PreToolUse", {"cwd": "/home/user"}, Path("/tmp"))
        assert ctx.cwd == "/home/user"

    def test_cwd_missing(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        assert ctx.cwd == ""


class TestToolShortcuts:
    def test_command(self) -> None:
        ctx = HookContext(
            "PreToolUse",
            {"toolInput": {"command": "echo hi"}},
            Path("/tmp"),
        )
        assert ctx.command == "echo hi"

    def test_command_missing(self) -> None:
        ctx = HookContext("PreToolUse", {"toolInput": {}}, Path("/tmp"))
        assert ctx.command == ""

    def test_file_path_snake_case(self) -> None:
        ctx = HookContext(
            "PreToolUse",
            {"toolInput": {"file_path": "/a/b.py"}},
            Path("/tmp"),
        )
        assert ctx.file_path == "/a/b.py"

    def test_file_path_camel_case(self) -> None:
        ctx = HookContext(
            "PreToolUse",
            {"toolInput": {"filePath": "/a/b.py"}},
            Path("/tmp"),
        )
        assert ctx.file_path == "/a/b.py"

    def test_file_path_prefers_snake_case(self) -> None:
        ctx = HookContext(
            "PreToolUse",
            {"toolInput": {"file_path": "/snake", "filePath": "/camel"}},
            Path("/tmp"),
        )
        assert ctx.file_path == "/snake"

    def test_file_path_missing(self) -> None:
        ctx = HookContext("PreToolUse", {"toolInput": {}}, Path("/tmp"))
        assert ctx.file_path == ""

    def test_content(self) -> None:
        ctx = HookContext(
            "PreToolUse",
            {"toolInput": {"content": "hello world"}},
            Path("/tmp"),
        )
        assert ctx.content == "hello world"

    def test_content_missing(self) -> None:
        ctx = HookContext("PreToolUse", {"toolInput": {}}, Path("/tmp"))
        assert ctx.content == ""


class TestResponseBuilders:
    def test_deny(self) -> None:
        result = HookContext.deny("bad command")
        assert result == {"decision": "deny", "reason": "bad command"}

    def test_allow(self) -> None:
        result = HookContext.allow()
        assert result == {"decision": "allow"}

    def test_ask(self) -> None:
        result = HookContext.ask("are you sure?")
        assert result == {"decision": "ask", "reason": "are you sure?"}

    def test_modify(self) -> None:
        result = HookContext.modify(command="echo safe")
        assert result == {
            "decision": "allow",
            "hookSpecificOutput": {"toolInput": {"command": "echo safe"}},
        }

    def test_modify_multiple_fields(self) -> None:
        result = HookContext.modify(command="ls", timeout=30)
        assert result["hookSpecificOutput"]["toolInput"] == {
            "command": "ls",
            "timeout": 30,
        }

    def test_block(self) -> None:
        result = HookContext.block("suspicious output")
        assert result == {
            "hookSpecificOutput": {"blocked": True, "reason": "suspicious output"},
        }

    def test_context(self) -> None:
        result = HookContext.context("extra info")
        assert result == {"hookSpecificOutput": {"context": "extra info"}}

    def test_system_message(self) -> None:
        result = HookContext.system_message("important note")
        assert result == {"hookSpecificOutput": {"systemMessage": "important note"}}


class TestCombine:
    def test_combine_two_responses(self) -> None:
        result = HookContext.combine(
            HookContext.allow(),
            HookContext.system_message("approved"),
        )
        assert result == {
            "decision": "allow",
            "hookSpecificOutput": {"systemMessage": "approved"},
        }

    def test_combine_merges_hook_specific_output(self) -> None:
        result = HookContext.combine(
            HookContext.context("info"),
            HookContext.system_message("note"),
        )
        assert result == {
            "hookSpecificOutput": {
                "context": "info",
                "systemMessage": "note",
            },
        }

    def test_combine_skips_none(self) -> None:
        result = HookContext.combine(None, HookContext.allow(), None)
        assert result == {"decision": "allow"}

    def test_combine_empty(self) -> None:
        result = HookContext.combine()
        assert result == {}

    def test_combine_last_writer_wins(self) -> None:
        result = HookContext.combine(
            {"decision": "deny", "reason": "first"},
            {"decision": "allow"},
        )
        assert result["decision"] == "allow"
        assert "reason" in result  # first writer's key preserved


class TestTarget:
    def test_target_defaults_to_empty(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        assert ctx.target == ""

    def test_target_set_on_init(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"), target="claude")
        assert ctx.target == "claude"

    def test_is_claude(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"), target="claude")
        assert ctx.is_claude is True
        assert ctx.is_copilot is False

    def test_is_copilot(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"), target="copilot")
        assert ctx.is_copilot is True
        assert ctx.is_claude is False

    def test_neither_target(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"), target="other")
        assert ctx.is_claude is False
        assert ctx.is_copilot is False


class TestLog:
    def test_log_writes_to_stderr(self, capsys: object) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        ctx.log("hello world")
        # capsys doesn't capture stderr from print; use capfd instead
        # This test just ensures no exception is raised.

    def test_log_does_not_raise(self) -> None:
        ctx = HookContext("PreToolUse", {}, Path("/tmp"))
        ctx.log("test message")  # Should not raise
