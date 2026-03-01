"""Handler discovery and dispatch from a loaded module."""

from __future__ import annotations

import re
import types
from typing import Any, Callable

from .decorators import _DEFAULT_ATTR, _TOOL_ATTR

# Type aliases for clarity.
_HandlerFn = Callable[..., Any]
_ToolHandlers = list[tuple[list[re.Pattern[str]], _HandlerFn]]


def _find_handlers(
    mod: types.ModuleType,
) -> tuple[_ToolHandlers, _HandlerFn | None]:
    """Scan *mod* for ``@tool`` and ``@default`` decorated functions.

    Args:
        mod: A loaded Python module to scan.

    Returns:
        A ``(tool_handlers, default_handler)`` tuple where *tool_handlers* is
        a list of ``(compiled_patterns, fn)`` pairs and *default_handler* is
        either a callable or ``None``.
    """
    tool_handlers: _ToolHandlers = []
    default_handler: _HandlerFn | None = None

    for name in dir(mod):
        obj = getattr(mod, name)
        if not callable(obj):
            continue
        patterns = getattr(obj, _TOOL_ATTR, None)
        if patterns is not None:
            tool_handlers.append((patterns, obj))
        if getattr(obj, _DEFAULT_ATTR, False):
            default_handler = obj

    return tool_handlers, default_handler


def has_decorators(mod: types.ModuleType) -> bool:
    """Return ``True`` if *mod* contains any ``@tool`` or ``@default`` handlers.

    Args:
        mod: A loaded Python module to inspect.
    """
    for name in dir(mod):
        obj = getattr(mod, name)
        if callable(obj) and (
            getattr(obj, _TOOL_ATTR, None) is not None or getattr(obj, _DEFAULT_ATTR, False)
        ):
            return True
    return False


def dispatch_decorated(
    mod: types.ModuleType,
    tool_name: str,
    ctx: Any,
) -> Any:
    """Run the first matching ``@tool`` handler, or ``@default`` if none match.

    Args:
        mod: The hook module containing decorated handlers.
        tool_name: The tool name to match against ``@tool`` patterns.
        ctx: The :class:`~phaicaid.context.HookContext` instance.

    Returns:
        The handler's return value, or ``None`` if nothing ran.
    """
    tool_handlers, default_handler = _find_handlers(mod)

    for patterns, fn in tool_handlers:
        for pat in patterns:
            if pat.search(tool_name):
                return fn(ctx)

    if default_handler is not None:
        return default_handler(ctx)

    return None
