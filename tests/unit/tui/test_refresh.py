"""Catalog polling is scoped to the visible surface."""

from __future__ import annotations

from unittest.mock import MagicMock

from band_wezterm.tui.refresh import install_catalog_refresh


def test_catalog_refresh_skips_hidden_screen() -> None:
    screen = MagicMock()
    screen.is_current = False
    refresh = MagicMock()

    install_catalog_refresh(screen, refresh)

    callback = screen.set_interval.call_args.args[1]
    callback()
    refresh.assert_not_called()


def test_catalog_refresh_runs_for_visible_screen() -> None:
    screen = MagicMock()
    screen.is_current = True
    refresh = MagicMock()

    install_catalog_refresh(screen, refresh)

    callback = screen.set_interval.call_args.args[1]
    callback()
    refresh.assert_called_once()
