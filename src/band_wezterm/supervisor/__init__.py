"""Detached per-user supervisor for managed Band agent workers."""

from band_wezterm.supervisor.client import SupervisorClient
from band_wezterm.supervisor.lifecycle import ManagedAgentLifecycle
from band_wezterm.supervisor.protocol import WorkerRecord, WorkerState

__all__ = ["ManagedAgentLifecycle", "SupervisorClient", "WorkerRecord", "WorkerState"]
