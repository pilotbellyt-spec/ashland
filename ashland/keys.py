# Global hotkeys read from /dev/input.

from __future__ import annotations
import glob
import os
import select
import struct
from collections.abc import Callable

EV_KEY = 0x01
_EVENT = "llHHi"  # struct input_event on x86_64
_SIZE = struct.calcsize(_EVENT)

KEY_CODES = {
    "ESC": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9,
    "9": 10, "0": 11, "MINUS": 12, "EQUAL": 13, "BACKSPACE": 14, "TAB": 15,
    "Q": 16, "W": 17, "E": 18, "R": 19, "T": 20, "Y": 21, "U": 22, "I": 23,
    "O": 24, "P": 25, "RETURN": 28, "ENTER": 28, "A": 30, "S": 31, "D": 32,
    "F": 33, "G": 34, "H": 35, "J": 36, "K": 37, "L": 38, "SEMICOLON": 39,
    "Z": 44, "X": 45, "C": 46, "V": 47, "B": 48, "N": 49, "M": 50,
    "SPACE": 57, "UP": 103, "LEFT": 105, "RIGHT": 106, "DOWN": 108,
}
MODS = {"SHIFT": {42, 54}, "CTRL": {29, 97}, "ALT": {56, 100},
        "SUPER": {125, 126}, "META": {125, 126}, "LOGO": {125, 126}}
_MOD_CODES = set().union(*MODS.values())


class HotkeyListener:
    def __init__(self, binds: list[tuple[set[str], str, str]],
                 dispatch: Callable[[str], object]):
        self.dispatch = dispatch
        self.binds = [(frozenset(m.upper() for m in mods), KEY_CODES[key.upper()], action)
                      for mods, key, action in binds if key.upper() in KEY_CODES]
        self._held: set[int] = set()

    def _chord_held(self, needed: frozenset) -> bool:
        wanted = set().union(*(MODS[m] for m in needed)) if needed else set()
        held = self._held & _MOD_CODES
        return all(MODS[m] & held for m in needed) and not held - wanted

    def run(self) -> None:
        poller, fds = select.poll(), []
        for path in sorted(glob.glob("/dev/input/event*")):
            if os.access(path, os.R_OK):
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                fds.append(fd)
                poller.register(fd, select.POLLIN)
        if not fds:
            raise RuntimeError("no readable /dev/input/event* devices")
        while True:
            for fd, _ in poller.poll():
                try:
                    data = os.read(fd, _SIZE * 64)
                except OSError:
                    continue
                for off in range(0, len(data) - _SIZE + 1, _SIZE):
                    _, _, kind, code, value = struct.unpack_from(_EVENT, data, off)
                    if kind != EV_KEY:
                        continue
                    if code in _MOD_CODES:
                        if value:
                            self._held.add(code)
                        else:
                            self._held.discard(code)
                    elif value == 1:  # key down, ignoring auto-repeat
                        for mods, key, action in self.binds:
                            if code == key and self._chord_held(mods):
                                self.dispatch(action)
