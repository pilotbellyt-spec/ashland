# ashland

A tiling window manager for ChromeOS.

## Install

```bash
bash install.sh
sudo bash enable-cdp.sh   # adds --remote-debugging-port, restarts the session
ashland start
```

Note: the second command signs you out.

`ashland start` detaches and logs to `~/.cache/ashland.log`.

## Keybinds

All keybinds are Search+Shift.

| Keybind | Action |
| --- | --- |
| Enter | spawn window |
| Q | kill window |
| J / K | focus next / prev |
| Arrows | focus by direction |
| H / L | swap with neighbour |
| F | toggle floating |
| D / M / G / O | dwindle / master / grid / monocle |
| Minus / Equals | master ratio |
| R | retile |

## Layouts

| Name | Behaviour |
| --- | --- |
| dwindle | each new window splits the largest pane |
| master | one master, the rest stacked beside it |
| grid | equal cells, fits the most windows |
| monocle | one window fullscreen, the rest minimised |

## Commands

```bash
ashland start              # background, survives the terminal
ashland state              # layout, capacity, window list
ashland layout grid
ashland focus right        # next | prev | left | right | up | down
ashland movewin left
ashland float
ashland gaps 8 16          # inner, outer
ashland masterratio +0.05
ashland workarea           # re-scan the display and retile
ashland quit
```

## Known issues

- ashland works on Chrome and PWA windows only.

## Config

`~/.config/ashland/ashland.conf`, generated from the defaults with a note on each
option. Edit and run `ashland retile`.

## Uninstall

```bash
ashland quit
sudo bash enable-cdp.sh --disable
```

## Source

```
ashland/
  layouts.py   geometry, capacity, gaps
  cdp.py       websocket and protocol client
  core.py      window model, tiling, focus, socket server
  keys.py      evdev keybinds
  config.py    settings and defaults
  __main__.py  CLI
```
