# Publishing rmon to the Snap Store

This walks through taking the snap from "builds locally" to "live on
the Snap Store". Run all of this on an Ubuntu 24.04 machine (or a VM)
— snap builds and installs need real snapd.

## 0. One-time setup

```sh
sudo snap install snapcraft --classic
sudo snap install lxd
sudo lxd init --auto
sudo usermod -aG lxd "$USER"
```

That last line adds you to the `lxd` group, which snapcraft needs in
order to talk to the LXD daemon without `sudo` — **log out and back in
(or open a fresh terminal) before continuing**, group membership only
takes effect in new login sessions. (`newgrp lxd` also works to pick
it up in your *current* shell, without a full logout.)

You'll also need an [Ubuntu One account](https://login.ubuntu.com/) —
that's what the Snap Store uses for publisher identity.

## 1. Build and smoke-test locally

```sh
cd rmon
snapcraft pack
sudo snap install ./rmon_0.1.0_amd64.snap --dangerous
rmon &
```

If LXD errors out (permission errors, or "Timed out waiting for
networking to be ready" -- both common, especially in VMs/containers),
build straight on the host instead, skipping LXD entirely:

```sh
snapcraft pack --destructive-mode
```

This installs the build/stage packages directly onto your machine via
apt rather than in a throwaway container. Fine for getting a snap
built and tested; if you want a fully clean/reproducible build later
(e.g. for CI), it's worth coming back and sorting out the LXD network
issue instead (it's very often IPv6-on-the-bridge related).

Check:
- The indicator icon appears in the top bar with a live-updating
  label.
- The dropdown shows per-core CPU, memory and swap detail.
- Preferences opens, changing the interval/toggles takes effect and
  survives `snap restart rmon` (proves the config file location is
  writable under confinement).
- `snap connections rmon` — everything the app plugs should already
  show as connected (the `gnome` extension's interfaces auto-connect).
- `snap run --shell rmon` if you need to poke around inside the
  confinement sandbox.

Remove the dangerous install before moving on:

```sh
sudo snap remove rmon
```

## 2. Register the name

```sh
snapcraft login
snapcraft register rmon
```

If `rmon` is taken by the time you do this, check
`snapcraft register --help` for the "similar name"/legacy dispute
process, or pick a different name and update `snap/snapcraft.yaml`
(`name:`), `snap/gui/*`, and the desktop file accordingly.

## 3. Push a build

```sh
snapcraft upload rmon_0.1.0_amd64.snap --release=edge
```

This uploads and releases to the `edge` channel so you (and anyone you
share the `edge` install command with) can test the exact artifact
that's headed to the store, before it's discoverable as a stable
release:

```sh
sudo snap install rmon --edge
```

## 4. Fill in the store listing

In the [Snap Store developer dashboard](https://snapcraft.io/rmon) (or
via `snapcraft`'s metadata commands), add:

- **Icon**: already embedded via `icon: data/icons/rmon.svg` in
  `snapcraft.yaml` / mirrored in `snap/gui/rmon.svg` — double-check it
  rendered correctly on the listing page.
- **Screenshots**: at least one, ideally showing the top bar label
  *and* the open dropdown. 1280x800 or similar works well.
- **Summary/description**: already sourced from `snapcraft.yaml`;
  tweak in the dashboard if you want store-specific copy without
  rebuilding.
- **Category**: "Utilities" fits.
- **Contact/source links**: already set via `contact:`, `issues:`,
  `source-code:` in `snapcraft.yaml`.

## 5. Promote to stable

Once you're happy with the edge build:

```sh
snapcraft release rmon <revision> stable
```

(`<revision>` comes from `snapcraft status rmon`.)

## 6. Automated review notes

`rmon` requests only the interfaces the `gnome` extension adds by
default (desktop, desktop-legacy, wayland, x11, gsettings, etc.) plus
whatever `stage-packages` pull in at build time — it does **not**
request `network`, `system-observe`, or `home`. Strict-confinement
snaps that only use auto-connecting interfaces typically clear the
Snap Store's automated review and go live within minutes of upload;
manual review only kicks in if you later add a manually-connected
interface.

## Future releases

Bump `version:` in `snap/snapcraft.yaml` (and `rmon/__init__.py`'s
`__version__` to keep the About dialog in sync), then repeat steps 1
and 3 (`snapcraft` → `snapcraft upload rmon_<version>_amd64.snap
--release=edge`, promote once verified).
