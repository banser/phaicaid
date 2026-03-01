"""phaicaid — Python Hooks for AI Coding Assistant: Interface and Daemon."""

from __future__ import annotations

from .context import HookContext
from .decorators import default, tool

__all__ = ["HookContext", "tool", "default"]
__version__ = "0.1.0"
