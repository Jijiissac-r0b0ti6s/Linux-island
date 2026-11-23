# Testing Linux Island on Windows

This Windows version was built and unit-tested on Linux but has **not run on a real Windows computer
yet**. This guide is for that first check. It needs Windows 10 or 11 on a 64-bit PC; there's nothing else
to install.

## Install

1. Copy `linux-island-<version>-windows-x64.zip` to the laptop and unzip it (right-click > Extract All).
2. In the unzipped folder, double-click **install.cmd**. If Windows shows "Windows protected your PC", choose
   More info > Run anyway. The package isn't signed yet.
3. It installs into `%LOCALAPPDATA%\Programs\Linux Island` for this user only, with no administrator needed:
   - Start menu entries: Linux Island, Linux Island Settings, Uninstall Linux Island.
   - It starts at sign-in.
   - It's listed in Settings > Apps.
4. The pill appears at the top of the screen. The first start opens Settings with the welcome card.

To remove it, use Start menu > Uninstall Linux Island, or Settings > Apps.

## First: the diagnose report

In the installed folder (`%LOCALAPPDATA%\Programs\Linux Island`), open a terminal (right-click > Open in
Terminal) and run:

```
.\linux-island.cmd --diagnose
```

It starts every part for 6 seconds and prints what each one finds. Before running it, play something
(Spotify or YouTube) and connect Bluetooth headphones if you have them. **Send back the whole output**,
especially any `FAILED` line or traceback.

## Then check each feature

| # | Try this | Expected |
| --- | --- | --- |
| 1 | Look at the top of the screen | The pill sits at the top centre, above every window |
| 2 | Click around the pill, on the area just outside it | Clicks reach the window underneath (only the pill itself takes clicks) |
| 3 | Rest the pointer on the pill, or click it | It opens: clock, battery, volume and brightness sliders |
| 4 | Play music in Spotify, YouTube (Chrome / Edge / Firefox) or Media Player | Artwork, title, artist; play / pause, next / previous and the seek bar work; the time keeps running |
| 5 | Change the volume with the keys, then with the island's slider; mute | The island's volume pop-up appears; the slider moves the real volume; the speaker icon follows |
| 6 | Change the brightness with the laptop's keys, then with the slider | The island's pop-up appears; the slider changes the panel's brightness |
| 7 | An external monitor that supports DDC/CI | Its own slider in the open pill changes the monitor's real brightness |
| 8 | Unplug and plug in the charger | Charger pop-up; the bolt turns green while charging |
| 9 | Open the Camera app, then a call with the microphone | Green dot for the camera, orange dot for the microphone |
| 10 | Connect / disconnect Bluetooth headphones | Device pop-up, with battery if Windows knows it |
| 11 | Minimise every window on a monitor (and also try Win+D) | The pill swoops into the home card; opening a window brings the pill back |
| 12 | Win+L, then sign in again | The black clock fade shows after signing in, then the pill comes back |
| 13 | `.\linux-island.cmd --lock` | Clock card and black fade, then the Windows lock screen |
| 14 | `.\linux-island.cmd --screensaver`, then move the mouse | Screensaver, then back to the pill |
| 15 | Leave it alone for the screensaver delay (Settings > Screensaver and lock) | Screensaver starts by itself |
| 16 | Settings: change colours, turn features off and on, pick monitors | Each change applies at once |
| 17 | Settings > General > Start on login off, then sign out and in | It doesn't start; turn it on again to undo |
| 18 | Unplug the external monitor while the pill is on it | The pill moves to the laptop screen, and back when it's plugged in again |
| 19 | Windows display scaling at 125 % / 150 % | The pill isn't blurry or misplaced |

## When something doesn't work: a debug log

```
.\linux-island.cmd --quit
set LINUX_ISLAND_DEBUG=1
.\linux-island.cmd > island-log.txt 2>&1
```

Use `$env:LINUX_ISLAND_DEBUG=1` instead of `set …` in PowerShell. Reproduce the problem, close the
terminal window (that stops it), and send `island-log.txt`. Start it normally again from the Start menu.

Other commands: `--status`, `--list-monitors`, `--settings`, `--quit`.

## Known differences from Linux

- **Two pop-ups:** Windows still shows its own volume and brightness pop-ups as well as the island's. You can
  turn the island's off in Settings > Features.
- **No lock key through the island:** Win+L can't be routed through the island. Locking that way skips the
  clock card before locking (the fade still plays after signing in). `linux-island.cmd --lock` plays the
  full animation, and can be put on a keyboard shortcut through a desktop shortcut's "Shortcut key".
- **External monitor brightness:** it needs DDC/CI (most monitors have it, sometimes switched off in the
  monitor's own menu). Monitors without it get no slider; there is no software dimming on Windows yet.
- **Bluetooth battery:** only shown when Windows itself shows the level in Settings > Bluetooth.
- **Not signed:** the package isn't signed, so Windows SmartScreen may warn the first time.

## Where things are

| | |
| --- | --- |
| Program | `%LOCALAPPDATA%\Programs\Linux Island` (Python 3.12 and Qt are inside, in `python\`) |
| Settings | `%APPDATA%\linux-island\config.json` |
| Start at sign-in | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value "Linux Island" |
