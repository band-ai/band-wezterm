"""Room accent colors — same hashing as identity.py, disjoint palette."""

from __future__ import annotations

from functools import lru_cache
from typing import Final
from uuid import UUID

from band_wezterm.identity import hash_string

# Disjoint from agent avatar hues: denser grid, no shared reserved-band filter,
# and a fixed lightness/saturation pair that reads cooler/lighter than agents.
ROOM_HUE_BUCKET_COUNT: Final = 12
ROOM_SATURATION: Final = 0.42
ROOM_LIGHTNESS: Final = 0.58


def _room_hues() -> tuple[float, ...]:
    step = 360.0 / ROOM_HUE_BUCKET_COUNT
    return tuple(bucket * step for bucket in range(ROOM_HUE_BUCKET_COUNT))


ROOM_HUES: Final = _room_hues()


def _hsl_to_hex(hue: float, saturation: float, lightness: float) -> str:
    chroma = saturation * min(lightness, 1.0 - lightness)

    def channel(n: float) -> str:
        k = (n + hue / 30.0) % 12.0
        value = lightness - chroma * max(-1.0, min(k - 3.0, 9.0 - k, 1.0))
        return f"{round(255 * value):02x}"

    return f"#{channel(0)}{channel(8)}{channel(4)}"


@lru_cache(maxsize=512)
def room_accent(room_id: UUID | str) -> str:
    """Deterministic room accent hex — palette disjoint from agent_accent()."""
    hue = ROOM_HUES[hash_string(f"room|{room_id}") % len(ROOM_HUES)]
    return _hsl_to_hex(hue, ROOM_SATURATION, ROOM_LIGHTNESS)
