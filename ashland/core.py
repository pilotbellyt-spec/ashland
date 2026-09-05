# The wm, keep ash's windows tiled

from __future__ import annotations
import json
import os
import socket
import threading
import time
from contextlib import suppress

from . import layouts
from .cdp import CDP, CDPError
from .config import Config

FALLBACK_AREA = (0, 0, 1366, 720)
# ash rounds geometry, so bounds within this many px count as already placed.
PLACED_EPSILON_PX = 2
WORK_AREA_JS = ("JSON.stringify([screen.availLeft|0, screen.availTop|0,"
                " screen.availWidth, screen.availHeight])")
DIRECTIONS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}


def socket_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "ashland.sock")


def _centre(b: dict) -> tuple[float, float]:
    return b["left"] + b["width"] / 2, b["top"] + b["height"] / 2


class WindowManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cdp = CDP(port=cfg.cdp_port)
        self.layout = cfg.layout
        self.gaps_in, self.gaps_out = cfg.gaps_in, cfg.gaps_out
        self.master_ratio, self.dwindle_ratio = cfg.master_ratio, cfg.dwindle_ratio
        self.min_w, self.min_h = cfg.min_width, cfg.min_height
        self.windows: dict[int, dict] = {}
        self.order: list[int] = []
        self.floating: set[int] = set()
        self.focus_idx = 0
        self.work_area: tuple | None = None
        self.running = True
        self.lock = threading.RLock()
        self._sessions: dict[str, str] = {}
        self._timer: threading.Timer | None = None
        self._timer_lock = threading.Lock()  # never hold this across a CDP call

    def connect(self, retries: int = 5) -> dict:
        for attempt in range(retries):
            try:
                info = self.cdp.connect()
                self.cdp.on_event = self._on_event
                self.cdp.send("Target.setDiscoverTargets", {"discover": True})
                return info
            except (OSError, CDPError) as e:
                if attempt == retries - 1:
                    raise CDPError(f"no CDP on 127.0.0.1:{self.cfg.cdp_port} ({e})\n"
                                   "  enable it once: sudo bash enable-cdp.sh")
                time.sleep(1.5)

    def _on_event(self, msg: dict) -> None:
        if msg["method"] in ("Target.targetCreated", "Target.targetDestroyed"):
            self.schedule_retile()

    def schedule_retile(self, delay: float = 0.35) -> None:
        with self._timer_lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(delay, self._retile_quietly)
            self._timer.daemon = True
            self._timer.start()

    def _retile_quietly(self) -> None:
        with suppress(CDPError):
            self.retile()

    def refresh(self) -> None:
        wins: dict[int, dict] = {}
        for t in self.cdp.send("Target.getTargets")["targetInfos"]:
            if t["type"] not in ("page", "app"):
                continue
            if t["url"].startswith(("devtools://", "chrome-extension://")):
                continue
            try:
                r = self.cdp.send("Browser.getWindowForTarget", {"targetId": t["targetId"]})
            except CDPError:
                if not self.cdp.alive:
                    raise
                continue
            win = wins.setdefault(r["windowId"],
                                  {"targets": [], "bounds": r["bounds"], "title": t["title"]})
            win["targets"].append(t["targetId"])
        with self.lock:
            self.windows = wins
            self.order = ([w for w in self.order if w in wins]
                          + [w for w in wins if w not in self.order])
            self.floating &= set(wins)
            if self.order:
                self.focus_idx %= len(self.order)

    def _ask_page_for_work_area(self) -> tuple | None:
        """screen.avail* is ash's work area, shelf excluded, in window-bounds units."""
        for win in list(self.windows.values()):
            for tid in win["targets"]:
                try:
                    sid = self._sessions.get(tid) or self.cdp.send(
                        "Target.attachToTarget",
                        {"targetId": tid, "flatten": True})["sessionId"]
                    self._sessions[tid] = sid
                    r = self.cdp.send("Runtime.evaluate",
                                      {"expression": WORK_AREA_JS, "returnByValue": True},
                                      session_id=sid)
                    x, y, w, h = json.loads(r["result"]["value"])
                    if w and h:
                        return x, y, w, h
                except (CDPError, KeyError, ValueError):
                    self._sessions.pop(tid, None)
        return None

    def get_work_area(self) -> tuple:
        self.work_area = self._ask_page_for_work_area() or self.work_area or FALLBACK_AREA
        return self.work_area

    def watch_display(self, interval: float = 4.0) -> None:
        while self.running:
            time.sleep(interval)
            area = self._ask_page_for_work_area()
            if area and area != self.work_area:
                print(f"ashland: display {self.work_area} -> {area}", flush=True)
                self.work_area = area
                self._retile_quietly()

    def _set_bounds(self, wid: int, **bounds) -> None:
        self.cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": bounds})

    def _place(self, wid: int, rect: tuple) -> None:
        x, y, w, h = rect
        b = self.windows[wid]["bounds"]
        if b.get("windowState", "normal") != "normal":
            self._set_bounds(wid, windowState="normal")  # bounds only apply when normal
        elif all(abs(b[k] - v) <= PLACED_EPSILON_PX for k, v in
                 (("left", x), ("top", y), ("width", w), ("height", h))):
            return
        self._set_bounds(wid, left=x, top=y, width=w, height=h)

    def _apply(self) -> str:
        ids = [w for w in self.order if w not in self.floating]
        if not ids:
            return "no tiled windows"
        area = self.get_work_area()
        rects = layouts.compute(self.layout, area, len(ids), gaps_in=self.gaps_in,
                                gaps_out=self.gaps_out, master_ratio=self.master_ratio,
                                dwindle_ratio=self.dwindle_ratio,
                                min_w=self.min_w, min_h=self.min_h)
        for wid, rect in zip(ids, rects):
            with suppress(CDPError):
                self._place(wid, rect)
        parked = ids[len(rects):]
        for wid in parked:
            if self.windows[wid]["bounds"].get("windowState") != "minimized":
                with suppress(CDPError):
                    self._set_bounds(wid, windowState="minimized")
        msg = f"tiled {len(rects)}/{len(ids)} windows ({self.layout}) in {area}"
        return msg + (f", {len(parked)} parked over capacity" if parked else "")

    def retile(self) -> str:
        with self.lock:
            self.refresh()
            return self._apply()

    def _focused(self) -> int | None:
        return self.order[self.focus_idx] if self.order else None

    def _unpark(self, wid: int) -> None:
        self.order.remove(wid)
        self.order.insert(0, wid)
        self._apply()

    def activate(self, wid: int) -> None:
        if self.windows[wid]["bounds"].get("windowState") == "minimized":
            self._unpark(wid)
        self.cdp.send("Target.activateTarget", {"targetId": self.windows[wid]["targets"][0]})
        self.focus_idx = self.order.index(wid)

    def _neighbour(self, direction: str) -> int | None:
        step, cur = DIRECTIONS.get(direction), self._focused()
        if step is None or cur is None:
            return None
        cx, cy = _centre(self.windows[cur]["bounds"])
        best = None
        for wid, win in self.windows.items():
            if wid == cur:
                continue
            x, y = _centre(win["bounds"])
            dx, dy = x - cx, y - cy
            along, across = (dx, dy) if step[0] else (dy, dx)
            if along * (step[0] or step[1]) <= 0 or abs(along) < abs(across):
                continue
            distance = dx * dx + dy * dy
            if best is None or distance < best[1]:
                best = (wid, distance)
        return best[0] if best else None

    def focus(self, where: str = "next") -> str:
        if not self.order:
            return "no windows"
        if where in ("next", "prev"):
            self.focus_idx = (self.focus_idx + (1 if where == "next" else -1)) % len(self.order)
        else:
            wid = self._neighbour(where)
            if wid is None:
                return f"no window {where}"
            self.focus_idx = self.order.index(wid)
        wid = self.order[self.focus_idx]
        self.activate(wid)
        return f"focused {wid} {self.windows[wid]['title'][:40]!r}"

    def movewin(self, where: str = "next") -> str:
        cur = self._focused()
        if cur is None:
            return "no windows"
        if where in ("next", "prev"):
            i = self.order.index(cur)
            j = (i + (1 if where == "next" else -1)) % len(self.order)
        else:
            other = self._neighbour(where)
            if other is None:
                return f"no window {where}"
            i, j = self.order.index(cur), self.order.index(other)
        self.order[i], self.order[j] = self.order[j], self.order[i]
        self.focus_idx = j
        self._apply()
        return f"moved {cur} {where}"

    def toggle_float(self) -> str:
        cur = self._focused()
        if cur is None:
            return "no windows"
        if cur in self.floating:
            self.floating.discard(cur)
            how = "tiled"
        else:
            self.floating.add(cur)
            how = "floating"
        self._apply()
        return f"{cur} now {how}"

    def spawn(self) -> str:
        r = self.cdp.send("Target.createTarget",
                          {"url": "chrome://newtab/", "newWindow": True})
        self.schedule_retile()
        return f"spawned {r['targetId']}"

    def killactive(self) -> str:
        cur = self._focused()
        if cur is None:
            return "no windows"
        for tid in self.windows[cur]["targets"]:
            with suppress(CDPError):
                self.cdp.send("Target.closeTarget", {"targetId": tid})
        self.schedule_retile()
        return f"closed window {cur}"

    def state(self) -> str:
        area = self.get_work_area()
        cap = layouts.capacity(self.layout, area, gaps_in=self.gaps_in,
                               gaps_out=self.gaps_out, master_ratio=self.master_ratio,
                               dwindle_ratio=self.dwindle_ratio,
                               min_w=self.min_w, min_h=self.min_h)
        out = [f"layout={self.layout} gaps={self.gaps_in}/{self.gaps_out} "
               f"master_ratio={self.master_ratio:.2f} area={area}",
               f"min window={self.min_w}x{self.min_h}  capacity={cap}  "
               f"windows={len(self.order)}"]
        for i, wid in enumerate(self.order):
            win = self.windows[wid]
            b = win["bounds"]
            tags = " [float]" if wid in self.floating else ""
            if b.get("windowState") == "minimized":
                tags += " [parked]"
            out.append(f"{'>' if i == self.focus_idx else ' '} {wid:>4} "
                       f"{b['left']:>5},{b['top']:>4} {b['width']:>5}x{b['height']:<5} "
                       f"{win['title'][:50]!r}{tags}")
        return "\n".join(out)

    def set_layout(self, name: str = "") -> str:
        if name not in layouts.LAYOUT_NAMES:
            return f"layout: one of {' '.join(layouts.LAYOUT_NAMES)}"
        self.layout = name
        return self._apply()

    def set_gaps(self, inner: str, outer: str | None = None) -> str:
        self.gaps_in = int(inner)
        if outer is not None:
            self.gaps_out = int(outer)
        return self._apply()

    def set_master_ratio(self, value: str) -> str:
        base = self.master_ratio if value[0] in "+-" else 0.0
        self.master_ratio = min(0.9, max(0.1, base + float(value)))
        return self._apply()

    def rescan(self) -> str:
        self.work_area = None
        return f"work area = {self.get_work_area()}; " + self._apply()

    def handle(self, line: str) -> str:
        cmd, *args = line.split() or [""]
        if cmd == "quit":
            self.running = False
            return "bye"
        actions = {"retile": self._apply, "state": self.state, "focus": self.focus,
                   "movewin": self.movewin, "float": self.toggle_float, "spawn": self.spawn,
                   "killactive": self.killactive, "layout": self.set_layout,
                   "gaps": self.set_gaps, "masterratio": self.set_master_ratio,
                   "workarea": self.rescan}
        if cmd not in actions:
            return f"unknown command {cmd!r} (have {' '.join(sorted(actions))} quit)"
        with self.lock:
            try:
                self.refresh()
                return actions[cmd](*args)
            except CDPError as e:
                return f"cdp error: {e}"
            except TypeError as e:
                return f"bad arguments for {cmd}: {e}"

    def serve(self) -> None:
        path = socket_path()
        if os.path.exists(path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(0.5)
            try:
                probe.connect(path)
                print("ashland: another daemon owns the socket", flush=True)
                self.running = False
                return
            except OSError:
                os.unlink(path)
            finally:
                probe.close()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        os.chmod(path, 0o600)
        srv.listen(8)
        srv.settimeout(0.5)
        while self.running:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            try:
                with conn:
                    conn.settimeout(30)
                    reply = self.handle(conn.recv(4096).decode(errors="replace"))
                    conn.sendall((reply + "\n").encode())
            except Exception as e:
                print(f"ashland: ipc: {type(e).__name__}: {e}", flush=True)
        srv.close()
        os.unlink(path)


def send_command(line: str, timeout: float = 30.0) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(socket_path())
    s.sendall(line.encode())
    chunks = []
    while chunk := s.recv(65536):
        chunks.append(chunk)
    s.close()
    return b"".join(chunks).decode(errors="replace").rstrip("\n")
