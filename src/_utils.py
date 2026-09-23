"""Shared utility functions for Termux Browser Pilot."""

import asyncio
import json
import os
import shutil


async def stop_owned_process(process, *, timeout=5.0):
    """Reap an owned child with bounded TERM/KILL waits, never a PID lookup."""
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass  # The child may have exited between returncode and the signal.
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await asyncio.wait_for(process.wait(), timeout=timeout)


def escape_js_string(value):
    """Escape a string for safe interpolation into JavaScript single-quoted strings.

    Uses json.dumps for correct escaping of all special characters, then
    converts the double-quoted JSON string to single-quoted JS format.
    Also strips null bytes and escapes backticks/template literals.
    """
    if not isinstance(value, str):
        value = str(value)
    # json.dumps handles: backslash, quotes, newlines, tabs, unicode escapes
    escaped = json.dumps(value)[1:-1]  # Strip surrounding double quotes
    # Additional JS-specific escapes not covered by JSON
    escaped = escaped.replace("\x00", "")       # Strip null bytes
    escaped = escaped.replace("'", "\\'")       # Single quotes (for JS '...')
    escaped = escaped.replace("`", "\\`")       # Backticks
    escaped = escaped.replace("${", "\\${")     # Template literal injection
    return escaped


def read_pid_file(path):
    """Read and validate a PID from a file. Returns int > 0 or None."""
    try:
        with open(path) as f:
            pid = int(f.read().strip())
        if pid <= 0:
            return None
        return pid
    except (ValueError, FileNotFoundError, OSError):
        return None


def require_binaries(*names):
    """Check that all required binaries exist. Raises RuntimeError if missing."""
    missing = [n for n in names if not shutil.which(n)]
    if missing:
        raise RuntimeError(
            f"Missing required binaries: {', '.join(missing)}. "
            f"Install with: pkg install {' '.join(missing)}"
        )


def validate_path(path, allowed_parent=None):
    """Validate and resolve a file path, preventing path traversal.

    Args:
        path: The path to validate.
        allowed_parent: If set, resolved path must be under this directory.
                        Defaults to current working directory.

    Returns:
        The resolved absolute path.

    Raises:
        ValueError: If the path escapes the allowed directory.
    """
    resolved = os.path.realpath(os.path.expanduser(path))
    if allowed_parent is None:
        allowed_parent = os.path.expanduser("~")
    allowed = os.path.realpath(allowed_parent)
    if not resolved.startswith(allowed + os.sep) and resolved != allowed:
        raise ValueError(
            f"Path '{path}' resolves outside allowed directory '{allowed}'"
        )
    return resolved
