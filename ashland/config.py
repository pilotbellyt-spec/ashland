"""Config at ~/.config/ashland/ashland.conf.

    layout = dwindle
    gaps_in = 6
    bind = SUPER SHIFT, RETURN, spawn
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field, fields

PATH = os.path.expanduser("~/.config/ashland/ashland.conf")

# ash ignores almost every SUPER+SHIFT chord, so ours arrive intact
DEFAULT_BINDS = [
    ("SUPER SHIFT", "RETURN", "spawn"), ("SUPER SHIFT", "Q", "killactive"),
    ("SUPER SHIFT", "J", "focus next"), ("SUPER SHIFT", "K", "focus prev"),
    ("SUPER SHIFT", "LEFT", "focus left"), ("SUPER SHIFT", "RIGHT", "focus right"),
    ("SUPER SHIFT", "UP", "focus up"), ("SUPER SHIFT", "DOWN", "focus down"),
    ("SUPER SHIFT", "H", "movewin prev"), ("SUPER SHIFT", "L", "movewin next"),
    ("SUPER SHIFT", "F", "float"), ("SUPER SHIFT", "R", "retile"),
    ("SUPER SHIFT", "D", "layout dwindle"), ("SUPER SHIFT", "M", "layout master"),
    ("SUPER SHIFT", "G", "layout grid"), ("SUPER SHIFT", "O", "layout monocle"),
    ("SUPER SHIFT", "MINUS", "masterratio -0.05"),
    ("SUPER SHIFT", "EQUAL", "masterratio +0.05"),
]


def _opt(default, help):
    return field(default=default, metadata={"help": help})


@dataclass
class Config:
    layout: str = _opt("dwindle", "dwindle, master, grid or monocle")
    gaps_in: int = _opt(6, "space between windows, in pixels")
    gaps_out: int = _opt(12, "space around the screen edge, in pixels")
    master_ratio: float = _opt(0.55, "how much width the big window gets, in master layout")
    dwindle_ratio: float = _opt(0.5, "where each split falls, in dwindle layout")
    cdp_port: int = _opt(9222, "must match the port in enable-cdp.sh")
    min_width: int = _opt(500, "Chrome refuses to be narrower than this. Measured, not guessed")
    min_height: int = _opt(150, "smallest window height to hand out")
    binds: list = field(
        default_factory=lambda: [(set(m.split()), k, a) for m, k, a in DEFAULT_BINDS])


def load(path: str | None = None) -> Config:
    cfg = Config()
    path = path or PATH
    if not os.path.exists(path):
        return cfg
    cast = {f.name: {"int": int, "float": float}.get(f.type, str) for f in fields(cfg)}
    binds = []
    with open(path) as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            key, value = (s.strip() for s in line.split("=", 1))
            if key == "bind":
                mods, _, rest = value.partition(",")
                name, _, action = rest.partition(",")
                if action:
                    binds.append((set(mods.replace("+", " ").split()),
                                  name.strip(), action.strip()))
            elif key in cast and key != "binds":
                setattr(cfg, key, cast[key](value))
    if binds:
        cfg.binds = binds
    return cfg


def default_text() -> str:
    cfg = Config()
    lines = ["# ashland settings. Edit, then run: ashland retile", ""]
    width = max(len(f.name) for f in fields(cfg) if f.name != "binds")
    for f in fields(cfg):
        if f.name == "binds":
            continue
        setting = f"{f.name:<{width}} = {getattr(cfg, f.name)}"
        lines.append(f"{setting:<28}# {f.metadata['help']}")
    lines += ["", "# Shortcuts. Format: bind = keys held, key pressed, what it does."]
    lines += [f"bind = {m}, {k}, {a}" for m, k, a in DEFAULT_BINDS]
    return "\n".join(lines) + "\n"
