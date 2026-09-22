"""`python -m band_wezterm.tui` — run a Band view in this pane."""

from __future__ import annotations

import argparse

from band_wezterm.tui.control_app import AppScreen, run_control_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="band_wezterm.tui")
    parser.add_argument("--room-id")
    parser.add_argument(
        "--screen",
        choices=(AppScreen.ROOMS.value, AppScreen.AGENTS.value),
        default=AppScreen.ROOMS.value,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_control_app(
        initial_room_id=args.room_id,
        initial_screen=AppScreen(args.screen),
    )


if __name__ == "__main__":
    raise SystemExit(main())
