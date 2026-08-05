#!/bin/sh
# Run rmon for local development.
#
# If your terminal was spawned by a snap-packaged app (VS Code's
# integrated terminal is the common case: `snap list | grep code`),
# that app injects its own bundled GTK/GDK-pixbuf/GIO module paths
# into the environment it hands to child shells -- built against its
# own base snap's (e.g. core20) older glibc. When our host python3 +
# GTK3 then tries to dlopen an icon loader or GTK module, it picks up
# the snap's incompatible .so instead of the host's, and dies with
# something like:
#
#   symbol lookup error: /snap/core20/current/lib/.../libpthread.so.0:
#   undefined symbol: __libc_pthread_init, version GLIBC_PRIVATE
#
# This is deliberately an explicit list, not a GTK_*/GDK_*/GIO_*
# name-pattern strip: a pattern match also catches GDK_BACKEND=x11,
# which VS Code sets on purpose and which turns out to be
# load-bearing here -- without it GTK falls back to auto-detecting
# Wayland (WAYLAND_DISPLAY is set alongside DISPLAY in this session)
# and crashes on an unrelated GSettings schema key lookup on this
# host. Verified by testing both forms directly: the pattern-based
# version reproducibly crashed, this exact list reproducibly doesn't.
# Stripping the vars below is harmless (a no-op) in a normal,
# non-snap terminal.
set -e
cd "$(dirname "$0")/.."
exec env \
  -u GTK_PATH -u GTK_EXE_PREFIX \
  -u GDK_PIXBUF_MODULE_FILE -u GDK_PIXBUF_MODULEDIR \
  -u GTK_IM_MODULE_FILE -u GIO_MODULE_DIR -u GSETTINGS_SCHEMA_DIR \
  -u LOCPATH \
  /usr/bin/python3 -m rmon "$@"
