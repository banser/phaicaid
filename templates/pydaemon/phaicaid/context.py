"""Rich hook context with auto-parsed properties and response builders."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _eprint(*args: object, **kwargs: Any) -> None:
    print(*args, file=sys.stderr, **kwargs)


class HookContext:
    """Wraps a hook event payload with convenient accessors and response builders.

    Every hook handler receives an instance of this class as its sole argument.
    Properties provide typed access to common payload fields, and static methods
    produce correctly-shaped response dicts that Claude Code / Copilot understand.

    Attributes:
        event: The hook event name (e.g. ``"PreToolUse"``).
        payload: The raw payload dict from the assistant.
        runtime_dir: Path to the ``.phaicaid`` runtime directory.
    """

    __slots__ = ("event", "payload", "runtime_dir", "target")

    def __init__(
        self,
        event: str,
        payload: dict[str, Any],
        runtime_dir: Path,
        target: str = "",
    ) -> None:
        self.event = event
        self.payload = payload
        self.runtime_dir = runtime_dir
        self.target = target

    # -- Target detection ------------------------------------------------------

    @property
    def is_claude(self) -> bool:
        """``True`` when the hook was triggered by Claude Code."""
        return self.target == "claude"

    @property
    def is_copilot(self) -> bool:
        """``True`` when the hook was triggered by GitHub Copilot."""
        return self.target == "copilot"

    # -- Logging ---------------------------------------------------------------

    def log(self, msg: str) -> None:
        """Log a message to stderr with ``[phaicaid]`` prefix."""
        _eprint(f"[phaicaid] {msg}")

    # -- Payload accessors -----------------------------------------------------

    @property
    def tool_name(self) -> str:
        """Name of the tool being called (e.g. ``"Bash"``, ``"Write"``)."""
        return self.payload.get("toolName", "")

    @property
    def tool_input(self) -> dict[str, Any]:
        """Full tool input dict."""
        return self.payload.get("toolInput", {})

    @property
    def tool_response(self) -> Any | None:
        """Tool response (available in PostToolUse events only)."""
        return self.payload.get("toolResponse")

    @property
    def session_id(self) -> str:
        """Current session identifier."""
        return self.payload.get("sessionId", "")

    @property
    def cwd(self) -> str:
        """Working directory of the assistant session."""
        return self.payload.get("cwd", "")

    # -- Tool-specific shortcuts -----------------------------------------------

    @property
    def command(self) -> str:
        """Bash tool shortcut: the shell command string."""
        return self.tool_input.get("command", "")

    @property
    def file_path(self) -> str:
        """Read/Write/Edit tool shortcut: the target file path."""
        return self.tool_input.get("file_path", "") or self.tool_input.get("filePath", "")

    @property
    def content(self) -> str:
        """Write tool shortcut: the file content being written."""
        return self.tool_input.get("content", "")

    # -- Response builders (PreToolUse / PermissionRequest) --------------------

    @staticmethod
    def deny(reason: str) -> dict[str, Any]:
        """Block the tool call.

        Args:
            reason: Human-readable explanation shown to the user.
        """
        return {"decision": "deny", "reason": reason}

    @staticmethod
    def allow() -> dict[str, Any]:
        """Explicitly approve the tool call."""
        return {"decision": "allow"}

    @staticmethod
    def ask(reason: str) -> dict[str, Any]:
        """Ask the user for confirmation before proceeding.

        Args:
            reason: Explanation shown in the confirmation prompt.
        """
        return {"decision": "ask", "reason": reason}

    @staticmethod
    def modify(**input_overrides: Any) -> dict[str, Any]:
        """Rewrite tool input fields and auto-approve.

        Args:
            **input_overrides: Key-value pairs to override in tool input.
        """
        return {
            "decision": "allow",
            "hookSpecificOutput": {"toolInput": input_overrides},
        }

    # -- Response builders (PostToolUse) ---------------------------------------

    @staticmethod
    def block(reason: str) -> dict[str, Any]:
        """Flag the tool output as problematic (PostToolUse).

        Args:
            reason: Explanation of why the output was flagged.
        """
        return {"hookSpecificOutput": {"blocked": True, "reason": reason}}

    # -- Response builders (general) -------------------------------------------

    @staticmethod
    def context(info: str) -> dict[str, Any]:
        """Inject additional context visible to the model.

        Args:
            info: Context string to inject.
        """
        return {"hookSpecificOutput": {"context": info}}

    @staticmethod
    def system_message(text: str) -> dict[str, Any]:
        """Inject a system-level message.

        Args:
            text: The system message content.
        """
        return {"hookSpecificOutput": {"systemMessage": text}}

    @staticmethod
    def combine(*responses: dict[str, Any] | None) -> dict[str, Any]:
        """Merge multiple response dicts into one.

        Later values win for top-level keys.  ``hookSpecificOutput`` dicts are
        merged shallowly rather than replaced.

        Args:
            *responses: Response dicts to merge (``None`` values are skipped).
        """
        merged: dict[str, Any] = {}
        for r in responses:
            if r is None:
                continue
            for k, v in r.items():
                if k == "hookSpecificOutput" and k in merged and isinstance(v, dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
        return merged
