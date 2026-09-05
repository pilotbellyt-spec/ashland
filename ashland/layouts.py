# tiling geometry.

from __future__ import annotations
import math
from typing import NamedTuple


class Rect(NamedTuple):
    x: int
    y: int
    w: int
    h: int

LAYOUT_NAMES = ("dwindle", "master", "grid", "monocle")


def _inset(r: Rect, d: int) -> Rect:
    return Rect(r.x + d, r.y + d, max(1, r.w - 2 * d), max(1, r.h - 2 * d))


def _split(r: Rect, ratio: float, min_w: int, min_h: int):
    x, y, w, h = r
    cuts = []
    a = int(w * ratio)
    if a >= min_w and w - a >= min_w and h >= min_h:
        cuts.append((w >= h, (Rect(x, y, a, h), Rect(x + a, y, w - a, h))))
    b = int(h * ratio)
    if b >= min_h and h - b >= min_h and w >= min_w:
        cuts.append((h > w, (Rect(x, y, w, b), Rect(x, y + b, w, h - b))))
    cuts.sort(key=lambda c: not c[0])
    return cuts[0][1] if cuts else None


def dwindle(area: Rect, n: int, ratio: float = 0.5, min_w: int = 1, min_h: int = 1) -> list[Rect]:
    """Splitting the largest pane, not the newest: a strict spiral quarters the
    width and dead-ends at 4 windows against a 500px floor at any screen size."""
    leaves = [Rect(*area)]
    while len(leaves) < n:
        i = max((i for i, r in enumerate(leaves) if _split(r, ratio, min_w, min_h)),
                key=lambda i: leaves[i].w * leaves[i].h, default=None)
        if i is None:
            break
        leaves[i:i + 1] = _split(leaves[i], ratio, min_w, min_h)
    return leaves[:n]


def master(area: Rect, n: int, ratio: float = 0.55, min_w: int = 1, min_h: int = 1) -> list[Rect]:
    x, y, w, h = area
    if n <= 1 or w < 2 * min_w or h < min_h:
        return [Rect(*area)][:n]
    mw = max(min_w, min(int(w * ratio), w - min_w))
    k = min(n - 1, max(1, h // min_h))
    base = h // k
    return [Rect(x, y, mw, h)] + [
        Rect(x + mw, y + i * base, w - mw, base if i < k - 1 else h - base * (k - 1))
        for i in range(k)]


def grid(area: Rect, n: int, min_w: int = 1, min_h: int = 1) -> list[Rect]:
    x, y, w, h = area
    cols = max(1, min(math.ceil(math.sqrt(n)), w // min_w or 1))
    rows = max(1, min(math.ceil(n / cols), h // min_h or 1))
    n, ch = min(n, cols * rows), h // rows
    out = []
    for i in range(n):
        r, c = divmod(i, cols)
        wide = min(cols, n - r * cols)
        cw = w // wide
        out.append(Rect(x + c * cw, y + r * ch,
                        cw if c < wide - 1 else w - cw * (wide - 1),
                        ch if r < rows - 1 else h - ch * (rows - 1)))
    return out


def compute(name: str, area: Rect, n: int, *, gaps_in: int = 6, gaps_out: int = 12,
            master_ratio: float = 0.55, dwindle_ratio: float = 0.5,
            min_w: int = 1, min_h: int = 1) -> list[Rect]:
    """Gapped rects for up to `n` windows. Returns fewer when they cannot all fit."""
    if name not in LAYOUT_NAMES:
        raise ValueError(f"unknown layout {name!r} (have {LAYOUT_NAMES})")
    if n <= 0:
        return []
    inner = _inset(Rect(*area), max(0, gaps_out - gaps_in // 2))
    tile_min_w, tile_min_h = min_w + gaps_in, min_h + gaps_in
    if name == "dwindle":
        raw = dwindle(inner, n, dwindle_ratio, tile_min_w, tile_min_h)
    elif name == "master":
        raw = master(inner, n, master_ratio, tile_min_w, tile_min_h)
    elif name == "grid":
        raw = grid(inner, n, tile_min_w, tile_min_h)
    else:
        raw = [inner]
    return [_inset(r, gaps_in // 2) for r in raw]


def capacity(name: str, area: Rect, *, probe: int = 64, **opts) -> int:
    return len(compute(name, area, probe, **opts))
