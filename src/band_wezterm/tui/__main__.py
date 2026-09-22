"""`python -m band_wezterm.tui` — run a Band view in this pane."""

from __future__ import annotations

import argparse

from band_wezterm.tui.control_app import run_control_app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="band_wezterm.tui")
    parser.add_argument("--room-id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_control_app(initial_room_id=args.room_id)


if __name__ == "__main__":
    raise SystemExit(main())
