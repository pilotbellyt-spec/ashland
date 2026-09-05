"""ashland: a tiling window manager layered on ChromeOS's ash.

  ashland start             run the manager in the background
  ashland daemon [--keys]   run it in the foreground
  ashland keys              hotkeys only, against a running daemon
  ashland doctor            check CDP and list ash's windows
  ashland <command> [args]  steer a running daemon:
      retile | state | workarea | quit
      layout dwindle|master|grid|monocle | gaps INNER [OUTER] | masterratio 0.6|+0.05
      focus next|prev|left|right|up|down | movewin next|prev|left|right|up|down
      float | spawn | killactive
"""

from __future__ import annotations
import os
import signal
import sys
import threading

from . import config
from .cdp import CDPError
from .core import WindowManager, send_command, socket_path


def doctor(cfg: config.Config) -> int:
    wm = WindowManager(cfg)
    try:
        info = wm.connect(retries=1)
    except CDPError as e:
        print(e)
        return 1
    print(f"connected to {info['Browser']} (protocol {info['Protocol-Version']})")
    wm.refresh()
    print(wm.state())
    return 0


def daemon(cfg: config.Config, with_keys: bool) -> int:
    wm = WindowManager(cfg)
    print(f"ashland: connected to {wm.connect()['Browser']}", flush=True)
    print(f"ashland: {wm.retile()}", flush=True)
    for loop in (wm.serve, wm.watch_display):
        threading.Thread(target=loop, daemon=True).start()
    if with_keys:
        from .keys import HotkeyListener
        hotkeys = HotkeyListener(cfg.binds, wm.handle)
        threading.Thread(target=hotkeys.run, daemon=True).start()
        print(f"ashland: {len(hotkeys.binds)} hotkeys armed via /dev/input", flush=True)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: setattr(wm, "running", False))
    idle = threading.Event()
    while wm.running and wm.cdp.alive:
        idle.wait(1.0)
    print("ashland: chrome went away" if not wm.cdp.alive else "ashland: bye")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cfg = config.load()
    if argv[0] == "doctor":
        return doctor(cfg)
    if argv[0] == "start":
        if os.fork():
            return 0
        os.setsid()
        log = os.open(socket_path().replace(".sock", ".log"),
                      os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
        os.dup2(log, 1)
        os.dup2(log, 2)
        return daemon(cfg, True)
    if argv[0] == "daemon":
        return daemon(cfg, "--keys" in argv)
    if argv[0] == "keys":
        from .keys import HotkeyListener
        HotkeyListener(cfg.binds, lambda a: print(send_command(a), flush=True)).run()
        return 0
    try:
        print(send_command(" ".join(argv)))
    except (FileNotFoundError, ConnectionRefusedError):
        print("ashland: no daemon running. Start one: ashland daemon --keys &")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
