"""Compatibility error for profiles created by earlier host versions."""

from __future__ import annotations


class NativeConsoleUnavailableError(RuntimeError):
    """A legacy native-console integration is unavailable."""
