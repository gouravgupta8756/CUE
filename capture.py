"""Screen capture helpers (PNG bytes) using mss."""

from __future__ import annotations

import mss
import mss.tools


def _grab(region: dict[str, int]) -> bytes:
    """Grab a screen region and return it as PNG bytes."""
    with mss.mss() as sct:
        shot = sct.grab(region)
    return mss.tools.to_png(shot.rgb, shot.size)


def list_monitors() -> list[dict[str, int]]:
    """Return monitors; index 0 is all screens combined, 1+ are individual."""
    with mss.mss() as sct:
        return [dict(m) for m in sct.monitors]


def capture_screen(monitor: int = 1) -> bytes:
    """Capture a monitor (0 = all screens) as PNG bytes."""
    monitors = list_monitors()
    if not 0 <= monitor < len(monitors):
        raise ValueError(f"monitor must be 0..{len(monitors) - 1}, got {monitor}")
    return _grab(monitors[monitor])


def capture_area(x: int, y: int, w: int, h: int) -> bytes:
    """Capture the rectangle at (x, y) of size w x h as PNG bytes."""
    if w <= 0 or h <= 0:
        raise ValueError("w and h must be positive")
    return _grab({"left": x, "top": y, "width": w, "height": h})


if __name__ == "__main__":
    for i, m in enumerate(list_monitors()):
        print(i, m)
    full, area = capture_screen(), capture_area(0, 0, 200, 200)
    assert full[:8] == area[:8] == b"\x89PNG\r\n\x1a\n"
    print(f"ok: screen={len(full)} bytes, area={len(area)} bytes")