"""Decorators for scoping hook handlers to specific tools."""

from __future__ import annotations

import re
from typing import Callable, TypeVar

# Marker attributes set on decorated functions.
_TOOL_ATTR = "_phaicaid_tool_patterns"
_DEFAULT_ATTR = "_phaicaid_default"

_F = TypeVar("_F", bound=Callable[..., object])


def tool(*patterns: str) -> Callable[[_F], _F]:
    """Decorator: run this handler only when ``tool_name`` matches a pattern.

    Plain strings are auto-anchored (``"Bash"`` becomes ``^Bash$``).
    If the pattern contains regex metacharacters it is used as-is.

    Args:
        *patterns: One or more tool name patterns to match against.

    Examples::

        @tool("Bash")
        def guard(ctx): ...

        @tool("Write", "Edit")
        def protect(ctx): ...

        @tool("mcp__.*")
        def log_mcp(ctx): ...
    """
    compiled: list[re.Pattern[str]] = []
    for p in patterns:
        # Auto-anchor plain identifiers (no regex metacharacters).
        if re.fullmatch(r"[A-Za-z0-9_]+", p):
            p = f"^{p}$"
        compiled.append(re.compile(p))

    def _wrap(fn: _F) -> _F:
        setattr(fn, _TOOL_ATTR, compiled)
        return fn

    return _wrap


def default(fn: _F) -> _F:
    """Decorator: fallback handler when no ``@tool`` matched.

    Example::

        @default
        def log_all(ctx):
            ctx.log(f"event: {ctx.tool_name}")
    """
    setattr(fn, _DEFAULT_ATTR, True)
    return fn
