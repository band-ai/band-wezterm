"""Detached per-user supervisor for managed Band agent workers."""

from band_wezterm.supervisor.client import SupervisorClient
from band_wezterm.supervisor.protocol import WorkerRecord, WorkerState

__all__ = ["SupervisorClient", "WorkerRecord", "WorkerState"]
