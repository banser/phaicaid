"""Tests for phaicaid._registry — handler discovery and dispatch."""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock

from phaicaid._registry import _find_handlers, dispatch_decorated, has_decorators
from phaicaid.context import HookContext
from phaicaid.decorators import default, tool


def _make_module(**attrs: object) -> types.ModuleType:
    """Create a fake module with the given attributes."""
    mod = types.ModuleType("fake_hook")
    for name, val in attrs.items():
        setattr(mod, name, val)
    return mod


class TestFindHandlers:
    def test_finds_tool_handler(self) -> None:
        @tool("Bash")
        def guard(ctx):  # type: ignore[no-untyped-def]
            pass

        mod = _make_module(guard=guard)
        tool_handlers, default_handler = _find_handlers(mod)
        assert len(tool_handlers) == 1
        assert tool_handlers[0][1] is guard
        assert default_handler is None

    def test_finds_default_handler(self) -> None:
        @default
        def fallback(ctx):  # type: ignore[no-untyped-def]
            pass

        mod = _make_module(fallback=fallback)
        tool_handlers, default_handler = _find_handlers(mod)
        assert len(tool_handlers) == 0
        assert default_handler is fallback

    def test_finds_both(self) -> None:
        @tool("Bash")
        def guard(ctx):  # type: ignore[no-untyped-def]
            pass

        @default
        def fallback(ctx):  # type: ignore[no-untyped-def]
            pass

        mod = _make_module(guard=guard, fallback=fallback)
        tool_handlers, default_handler = _find_handlers(mod)
        assert len(tool_handlers) == 1
        assert default_handler is fallback

    def test_empty_module(self) -> None:
        mod = _make_module()
        tool_handlers, default_handler = _find_handlers(mod)
        assert len(tool_handlers) == 0
        assert default_handler is None

    def test_ignores_non_callable(self) -> None:
        mod = _make_module(some_string="hello", some_int=42)
        tool_handlers, default_handler = _find_handlers(mod)
        assert len(tool_handlers) == 0
        assert default_handler is None


class TestHasDecorators:
    def test_true_with_tool(self) -> None:
        @tool("Bash")
        def guard(ctx):  # type: ignore[no-untyped-def]
            pass

        mod = _make_module(guard=guard)
        assert has_decorators(mod) is True

    def test_true_with_default(self) -> None:
        @default
        def fallback(ctx):  # type: ignore[no-untyped-def]
            pass

        mod = _make_module(fallback=fallback)
        assert has_decorators(mod) is True

    def test_false_with_plain_handle(self) -> None:
        def handle(payload, ctx):  # type: ignore[no-untyped-def]
            pass

        mod = _make_module(handle=handle)
        assert has_decorators(mod) is False

    def test_false_empty(self) -> None:
        mod = _make_module()
        assert has_decorators(mod) is False


class TestDispatchDecorated:
    def _ctx(self, tool_name: str = "Bash") -> HookContext:
        return HookContext(
            "PreToolUse",
            {"toolName": tool_name},
            Path("/tmp"),
        )

    def test_matches_tool(self) -> None:
        @tool("Bash")
        def guard(ctx):  # type: ignore[no-untyped-def]
            return ctx.deny("blocked")

        mod = _make_module(guard=guard)
        result = dispatch_decorated(mod, "Bash", self._ctx("Bash"))
        assert result == {"decision": "deny", "reason": "blocked"}

    def test_no_match_falls_to_default(self) -> None:
        @tool("Bash")
        def guard(ctx):  # type: ignore[no-untyped-def]
            return ctx.deny("blocked")

        @default
        def fallback(ctx):  # type: ignore[no-untyped-def]
            return ctx.allow()

        mod = _make_module(guard=guard, fallback=fallback)
        result = dispatch_decorated(mod, "Write", self._ctx("Write"))
        assert result == {"decision": "allow"}

    def test_no_match_no_default_returns_none(self) -> None:
        @tool("Bash")
        def guard(ctx):  # type: ignore[no-untyped-def]
            return ctx.deny("blocked")

        mod = _make_module(guard=guard)
        result = dispatch_decorated(mod, "Write", self._ctx("Write"))
        assert result is None

    def test_multiple_tool_patterns(self) -> None:
        @tool("Write", "Edit")
        def protect(ctx):  # type: ignore[no-untyped-def]
            return ctx.deny("protected")

        mod = _make_module(protect=protect)

        result_write = dispatch_decorated(mod, "Write", self._ctx("Write"))
        assert result_write is not None
        assert result_write["decision"] == "deny"

        result_edit = dispatch_decorated(mod, "Edit", self._ctx("Edit"))
        assert result_edit is not None
        assert result_edit["decision"] == "deny"

        result_bash = dispatch_decorated(mod, "Bash", self._ctx("Bash"))
        assert result_bash is None

    def test_regex_pattern(self) -> None:
        @tool("mcp__.*")
        def log_mcp(ctx):  # type: ignore[no-untyped-def]
            return {"logged": True}

        mod = _make_module(log_mcp=log_mcp)
        result = dispatch_decorated(
            mod, "mcp__wrike__get_tasks", self._ctx("mcp__wrike__get_tasks"),
        )
        assert result == {"logged": True}

    def test_first_matching_handler_wins(self) -> None:
        @tool("Bash")
        def first(ctx):  # type: ignore[no-untyped-def]
            return {"handler": "first"}

        @tool("Bash")
        def second(ctx):  # type: ignore[no-untyped-def]
            return {"handler": "second"}

        # dir() returns alphabetical order, so 'first' comes before 'second'.
        mod = _make_module(first=first, second=second)
        result = dispatch_decorated(mod, "Bash", self._ctx("Bash"))
        assert result is not None
        assert result["handler"] == "first"

    def test_empty_module_returns_none(self) -> None:
        mod = _make_module()
        result = dispatch_decorated(mod, "Bash", self._ctx("Bash"))
        assert result is None

    def test_handler_returning_none(self) -> None:
        @tool("Bash")
        def guard(ctx):  # type: ignore[no-untyped-def]
            return None

        mod = _make_module(guard=guard)
        result = dispatch_decorated(mod, "Bash", self._ctx("Bash"))
        assert result is None

    def test_default_only(self) -> None:
        @default
        def catch_all(ctx):  # type: ignore[no-untyped-def]
            return {"caught": ctx.tool_name}

        mod = _make_module(catch_all=catch_all)
        result = dispatch_decorated(mod, "Anything", self._ctx("Anything"))
        assert result == {"caught": "Anything"}
