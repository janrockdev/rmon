# rmon

A lightweight system monitor for the Ubuntu top bar. `rmon` shows a
compact, always-visible readout of CPU load, memory usage and swap
usage, with a dropdown for per-core detail and a few preferences.

```
CPU 23%  MEM 41%  SWAP 0%   ▾
```

No telemetry, no network access — it reads `/proc/stat` and
`/proc/meminfo` directly and that's it.

## How it works

- **Language/UI**: Python 3 + GTK3, using [AppIndicator](https://ubuntu.com/blog/what-is-appindicator)
  (`AyatanaAppIndicator3`) — the same mechanism most Ubuntu tray apps
  use, which the top bar renders via the "Ubuntu AppIndicators"
  GNOME Shell extension that ships enabled by default on Ubuntu.
- **Stats**: [rmon/stats.py](rmon/stats.py) is pure standard library
  (no GTK import) — it parses `/proc/stat` for per-core CPU deltas and
  `/proc/meminfo` for memory/swap. It's unit tested independently of
  the GUI (see [tests/test_stats.py](tests/test_stats.py)).
- **UI**: [rmon/app.py](rmon/app.py) owns the indicator, the dropdown
  menu (rebuilt on every tick — cheap at a 1-30s poll interval) and a
  small GTK preferences dialog.
- **Config**: a small JSON file, at `$SNAP_USER_COMMON/config.json`
  when running as a snap (survives snap refreshes) or
  `~/.config/rmon/config.json` otherwise.

## Local development (without building a snap)

You need PyGObject and the GTK/AppIndicator introspection data from
apt — installing `PyGObject` via pip alone won't have the right
system libraries behind it:

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 \
  gir1.2-ayatanaappindicator3-0.1 python3-gi-cairo
```

Then just run it from the repo root:

```sh
python3 -m rmon
```

**If your terminal is inside a snap-packaged app** (VS Code's
integrated terminal is the common case — check with `snap list | grep
code`), that app injects its own bundled GTK/GDK-pixbuf module paths
into every child shell it spawns, built against its own base snap's
older glibc. Our host `python3` + GTK3 can then dlopen one of *those*
incompatible libraries instead of the host's own, and crash with
something like:

```
symbol lookup error: /snap/core20/current/lib/x86_64-linux-gnu/libpthread.so.0:
undefined symbol: __libc_pthread_init, version GLIBC_PRIVATE
```

Use [scripts/dev-run.sh](scripts/dev-run.sh) instead — it strips the
injected env vars before launching (harmless/no-op in a normal
terminal):

```sh
./scripts/dev-run.sh
```

Run the (GTK-free) unit tests any time with:

```sh
python3 -m unittest discover -s tests -v
```

## Building the snap

Requires [snapcraft](https://snapcraft.io/docs/snapcraft-overview)
(`sudo snap install snapcraft --classic`) and either LXD or multipass
as the build backend. If you install LXD (`sudo snap install lxd`),
you also need to be in the `lxd` group (`sudo usermod -aG lxd $USER`,
then start a new shell/log session for it to take effect) before
snapcraft can use it.

```sh
snapcraft pack        # builds ./rmon_0.1.0_amd64.snap
```

If LXD gives you grief (permission errors, or "Timed out waiting for
networking to be ready" -- both common, especially in VMs/containers),
skip the isolated build and build straight on your host instead:

```sh
snapcraft pack --destructive-mode
```

This installs the build/stage packages (GTK, AppIndicator, etc.)
directly onto your machine via apt rather than in a throwaway
container -- fine for a personal dev box, just not as pristine an
environment as the LXD path.

Install and try it locally before publishing anything:

```sh
sudo snap install ./rmon_0.1.0_amd64.snap --dangerous
rmon &
sudo snap remove rmon   # when you're done poking at it
```

If the indicator doesn't show up, confirm the "Ubuntu AppIndicators"
extension is enabled (`gnome-extensions list` /
Extension Manager app) — it's on by default on stock Ubuntu but can be
disabled.

## Publishing to the Snap Store

See [docs/PUBLISHING.md](docs/PUBLISHING.md) for the full step-by-step
(registering the name, `snapcraft upload`, store listing assets,
review process).

## Project layout

```
rmon/                  Python package (stats collection + GTK UI)
data/                  Icons and the .desktop file shipped in the snap
bin/rmon-launch        Entry point the snap's `command:` invokes
snap/snapcraft.yaml    Snap packaging recipe (base: core24, strict confinement)
snap/gui/              Store metadata mirror of data/ (desktop + icon)
tests/                 Unit tests for rmon/stats.py (no GTK needed)
docs/PUBLISHING.md     Snap Store submission walkthrough
```

## License

MIT — see [LICENSE](LICENSE).
