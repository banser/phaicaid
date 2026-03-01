"""Tests for phaicaid.decorators — @tool and @default."""

from __future__ import annotations

from phaicaid.decorators import _DEFAULT_ATTR, _ORDER_ATTR, _TOOL_ATTR, default, tool


class TestToolDecorator:
    def test_sets_patterns_attribute(self) -> None:
        @tool("Bash")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        patterns = getattr(handler, _TOOL_ATTR)
        assert len(patterns) == 1

    def test_auto_anchors_plain_string(self) -> None:
        @tool("Bash")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        pat = getattr(handler, _TOOL_ATTR)[0]
        assert pat.pattern == "^Bash$"

    def test_preserves_regex(self) -> None:
        @tool("mcp__.*")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        pat = getattr(handler, _TOOL_ATTR)[0]
        assert pat.pattern == "mcp__.*"

    def test_multiple_patterns(self) -> None:
        @tool("Write", "Edit")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        patterns = getattr(handler, _TOOL_ATTR)
        assert len(patterns) == 2
        assert patterns[0].pattern == "^Write$"
        assert patterns[1].pattern == "^Edit$"

    def test_returns_original_function(self) -> None:
        def handler(ctx):  # type: ignore[no-untyped-def]
            return "value"

        wrapped = tool("Bash")(handler)
        assert wrapped is handler

    def test_plain_identifier_with_underscores(self) -> None:
        @tool("mcp__server_tool")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        pat = getattr(handler, _TOOL_ATTR)[0]
        assert pat.pattern == "^mcp__server_tool$"

    def test_regex_with_brackets(self) -> None:
        @tool("(Read|Write)")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        pat = getattr(handler, _TOOL_ATTR)[0]
        # Should NOT be auto-anchored since it contains regex chars.
        assert pat.pattern == "(Read|Write)"

    def test_matches_correctly(self) -> None:
        @tool("Bash")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        pat = getattr(handler, _TOOL_ATTR)[0]
        assert pat.search("Bash")
        assert not pat.search("BashExtra")
        assert not pat.search("PreBash")

    def test_regex_matches_mcp_tools(self) -> None:
        @tool("mcp__.*")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        pat = getattr(handler, _TOOL_ATTR)[0]
        assert pat.search("mcp__wrike__get_tasks")
        assert pat.search("mcp__ide__getDiagnostics")
        assert not pat.search("Bash")


class TestDefaultDecorator:
    def test_sets_default_attribute(self) -> None:
        @default
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        assert getattr(handler, _DEFAULT_ATTR) is True

    def test_returns_original_function(self) -> None:
        def handler(ctx):  # type: ignore[no-untyped-def]
            return "value"

        wrapped = default(handler)
        assert wrapped is handler

    def test_does_not_set_tool_attr(self) -> None:
        @default
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        assert getattr(handler, _TOOL_ATTR, None) is None


class TestOrderAttribute:
    """Issue 7: Decorators set monotonically increasing order attributes."""

    def test_sets_order_attribute(self) -> None:
        @tool("Bash")
        def handler(ctx):  # type: ignore[no-untyped-def]
            pass

        assert hasattr(handler, _ORDER_ATTR)
        assert isinstance(getattr(handler, _ORDER_ATTR), int)

    def test_order_is_monotonically_increasing(self) -> None:
        @tool("Bash")
        def first(ctx):  # type: ignore[no-untyped-def]
            pass

        @tool("Write")
        def second(ctx):  # type: ignore[no-untyped-def]
            pass

        @default
        def third(ctx):  # type: ignore[no-untyped-def]
            pass

        assert getattr(first, _ORDER_ATTR) < getattr(second, _ORDER_ATTR)
        assert getattr(second, _ORDER_ATTR) < getattr(third, _ORDER_ATTR)
