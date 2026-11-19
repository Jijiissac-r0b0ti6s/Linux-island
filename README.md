# Linux Island

A dynamic-island style pill at the top of the Linux desktop, on one monitor, several, or all of them.

- **Now playing**: artwork, title, an equaliser, play/pause, next/previous and a seek bar for any MPRIS player
  (Spotify, Firefox / YouTube, VLC, mpv…)
- **Pop-ups**: volume, brightness, charger, Bluetooth devices (with their battery) and headphones
- **Hover or click** the pill for the clock, battery, and volume and brightness sliders; scroll over it for volume
- **Camera and microphone indicators**: a green / orange dot while an app uses them
- **Home card**: when every window on a monitor is minimised, the pill swoops into a large card with the time, a
  calendar, battery, Bluetooth devices and per-monitor brightness
- **Screensaver and lock**: when idle (default 5 minutes) or locking, the pill swoops into a clock card and the screen
  fades to a black clock with what's playing and the battery, on every monitor (or only the pill's); any input (or
  unlocking) brings the pill back
- **Live icons**: the speaker's waves follow the volume, the sun's rays the brightness, the bolt turns yellow at
  50 % and red at 20 %
- **Brightness per monitor**: the laptop's real backlight, software dimming (`xrandr`) on external monitors
- **Follows the monitors**: if the chosen monitor is unplugged it moves to the primary one, and back again
- **Settings panel** for all of it, applied live

Runs on X11 desktops on any x86_64 distribution (developed and tested on Ubuntu 24.04 / GNOME 46).

## Download

Get the packages from the **Releases** page of this repository (each release has the `.deb`, the universal tarball
and `SHA256SUMS`). You don't need to clone the repository to use Linux Island.

## Install

Two packages are built for every release (`packaging/build.sh` builds them into `dist/`). Both run on any x86_64 distribution with **glibc 2.34+** and **Python 3.10 – 3.15**
(Ubuntu 22.04+, Debian 12+, Mint 21+, Pop!_OS 22.04+, Fedora 35+, Arch, Manjaro, openSUSE Tumbleweed, …); Qt 6
(PySide6) is bundled, nothing is tied to one release.

**Debian, Ubuntu, Mint, Pop!_OS, elementary, Zorin, …**

```bash
sudo apt install ./linux-island_0.3.1_amd64.deb
```

**Any other distribution** (Fedora, Arch, openSUSE, …): unpack the tarball and run its installer

```bash
tar xf linux-island-0.3.1-x86_64.tar.gz && cd linux-island-0.3.1-x86_64
sudo ./install.sh          # for everyone: /opt/linux-island, /usr/local/bin
./install.sh --user        # or just for you, no root: ~/.local
./install.sh --uninstall   # (add --user for a user install) remove it again
```

The installer checks Python and glibc and lists the few Qt libraries to install if they're missing
(`xcb-util-cursor` and friends on Fedora / Arch, `libxcb-cursor0` on Debian / openSUSE).

Right after installing, start it once from the app menu (**Linux Island**), or log out and back in. On its first start
it opens the settings with a short welcome, so the monitors and colours can be picked; after that it starts by itself
on every login.

**Desktops**: GNOME, KDE Plasma, Cinnamon, MATE, Xfce, … on **X11**. In a Wayland session the launcher runs it through
XWayland, where X11 can't see native Wayland windows (recent Chrome, Brave, VS Code, GNOME apps). For the home card
there, GNOME users turn on the **Linux Island helper** extension, which comes with the package: log out and back in
once after installing, then Settings > Screensaver and lock > Home card > Turn on. Without it, a Wayland session leaves
the home card out (rather than showing one that never goes back to the pill); everything else works either way.

## Settings

Open **Linux Island Settings** from the app menu, the gear in the open pill, or `linux-island --settings`:

| Page | |
| --- | --- |
| General | which monitors, start on login, clock format, gap above the pill |
| Appearance | colours from the album art or a fixed accent, accent and pill colours (presets or any colour), pop-up duration |
| Features | turn each part on or off: now playing, each pop-up, camera / mic dots, open on hover, scroll for volume, home card, lock animation |
| Screensaver and lock | screensaver on/off, on all monitors or only the pill's, delay, lock animation, using the island for GNOME's lock shortcut, home card height |
| About | version, where the settings live, restore defaults |

Settings are saved to `~/.config/linux-island/config.json` (only what differs from the defaults); the running island
applies changes as soon as the file changes, so editing it by hand works too.

## Command line

```bash
linux-island                    # start (only one runs per user)
linux-island --settings         # settings panel
linux-island --list-monitors
linux-island --monitors eDP-1,DP-1 --save
linux-island --screensaver      # screensaver now
linux-island --lock             # lock, with the clock card and fade first
linux-island --lock-shortcut on # GNOME: Ctrl+Alt+L goes through the island (off: give it back)
linux-island --autostart on|off
linux-island --status           # what the running island sees: lock, idle time, screensaver armed, …
```

GNOME always draws its lock screen above every window, so the island can't be *on* the lock screen. When locking
through the island (its shortcut or `--lock`), the clock card and black fade come first, then the lock screen;
locking any other way still gives the fade back after unlocking. If the island is removed, the shortcut falls back
to a plain `loginctl lock-session`.

## How it works

| | |
| --- | --- |
| Media | MPRIS over D-Bus (`jeepney`); position extrapolated locally because Firefox reports it only on pause / seek |
| Volume | `wpctl` (PipeWire) or `pactl`; reads only when the sound server announces a change (libpulse subscription) |
| Brightness | sysfs backlight written through systemd-logind (no root); `xrandr --brightness` on external monitors; GNOME's own idle dim / undim doesn't trigger the pop-up |
| Battery | `/sys/class/power_supply/BAT*` |
| Camera / mic | inotify on `/dev/video*` then a scan of open file handles / ALSA capture streams |
| Bluetooth | BlueZ `Device1` / `Battery1` |
| Windows | the GNOME helper extension when it's on (sees every window, Wayland too), else X11 events on the root and every application window |
| Lock / idle | `org.gnome.ScreenSaver` (else logind `LockedHint`), idle time from Mutter (else XScreenSaver) |
| Screensaver | the pill animates in its own small window; the full-screen black part is only faded by the compositor, so it stays smooth on 4K screens |

Measured idle on a laptop with a 4K external monitor: ~0.3 % of one CPU core, ~17 wake-ups per second, ~110 MB of
memory (PSS). Background threads are named `island-*` in `top -H` / `htop`.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/linux-island
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -t .    # tests
LINUX_ISLAND_DEBUG=1 .venv/bin/linux-island                                     # log decisions
```

Qt needs `libxcb-cursor0` on X11 (`sudo apt install libxcb-cursor0`).

| Path | |
| --- | --- |
| `linux_island/app.py` | windows, monitors, live settings, command line |
| `linux_island/settings.py`, `qml/Settings.qml` | the settings panel |
| `linux_island/config.py` | settings, their defaults and checks |
| `linux_island/system.py` | start on login, GNOME lock shortcut |
| `linux_island/services/` | media, audio, brightness, battery, camera, mic, Bluetooth, windows, lock / idle |
| `linux_island/qml/` | the island, its icons and the screensaver |
| `gnome-extension/` | the GNOME Shell helper (tells the island which monitors are empty, Wayland windows included) |
| `tests/` | unit and QML tests |
| `packaging/` | `packaging/build.sh` builds the `.deb` and the universal tarball (with `install.sh`) into `dist/` |

### Building the packages

```bash
packaging/build.sh
```

It copies PySide6, shiboken6 and jeepney from `.venv` (no network needed), leaves out Qt's developer tools,
translations and headers, and builds `dist/linux-island_<version>_amd64.deb`, `dist/linux-island-<version>-x86_64.tar.gz`
and `dist/SHA256SUMS`. The bundle is Python-version independent (abi3); the `.deb` byte-compiles it for the system's
Python on install.

## Status

- X11: working. Wayland needs a layer-shell surface (wlroots, KDE) or a GNOME Shell extension; not implemented.
- External-monitor brightness is software dimming; real backlight control would need DDC/CI (`ddcutil` and i2c access).
