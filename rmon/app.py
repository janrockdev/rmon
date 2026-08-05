"""rmon's GTK/AppIndicator front end.

Shows a compact CPU / memory / swap readout in the Ubuntu top bar, with
a dropdown for per-core detail and a couple of preferences. All the gi
(GObject introspection) imports live in this module only, so `stats.py`
stays importable/testable without GTK installed.
"""
from __future__ import annotations

import json
import os
import signal
from dataclasses import asdict, dataclass
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
except (ValueError, ImportError):
    # Older/non-Ubuntu systems may only have the original libappindicator3.
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3  # type: ignore[no-redef]

from gi.repository import GLib, Gtk

from . import __version__, stats

APP_ID = "rmon"
APP_NAME = "rmon"
PROJECT_URL = "https://github.com/janrock-dev/rmon"
AUTHOR = "Jan Rock <rock@linux.com>"

DEFAULT_INTERVAL = 2
MIN_INTERVAL = 1
MAX_INTERVAL = 30


def _running_as_our_snap() -> bool:
    """True only when *we* are the snap-confined process, not just any.

    `SNAP`/`SNAP_USER_DATA`/`SNAP_USER_COMMON` are set for every
    snap-confined process -- including, say, VS Code's own integrated
    terminal if that's how rmon happens to be launched in dev mode.
    Checking merely "is SNAP set" would then misread VS Code's snap
    paths as our own. `SNAP_NAME` is the one variable that actually
    names *which* snap is running, so that's what we key off of.
    """
    return os.environ.get("SNAP_NAME") == APP_NAME


def _data_dir() -> Path:
    """Where our icons/desktop assets live, inside or outside the snap."""
    if _running_as_our_snap():
        return Path(os.environ["SNAP"]) / "data"
    return Path(__file__).resolve().parent.parent / "data"


def _config_path() -> Path:
    """Pick a writable, per-user config location.

    SNAP_USER_COMMON survives snap refreshes (unlike SNAP_USER_DATA,
    which is versioned per-revision), so we prefer it when running as
    a snap. Outside the snap we fall back to XDG_CONFIG_HOME.
    """
    if _running_as_our_snap():
        root = Path(os.environ["SNAP_USER_COMMON"])
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        root = Path(xdg) / "rmon" if xdg else Path.home() / ".config" / "rmon"
    root.mkdir(parents=True, exist_ok=True)
    return root / "config.json"


def _autostart_desktop_path() -> Path:
    """Where a login-autostart entry for rmon must live to take effect.

    Under snap confinement this has to be exactly
    $SNAP_USER_DATA/.config/autostart -- that's the one location a
    strict-confinement snap is granted write access to for this
    purpose, matched against the `autostart:` key declared for this
    app in snap/snapcraft.yaml. Outside the snap, it's the ordinary
    XDG autostart directory that every Linux desktop session already
    watches, snap or not.
    """
    if _running_as_our_snap():
        root = Path(os.environ["SNAP_USER_DATA"]) / ".config" / "autostart"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        root = Path(xdg) / "autostart" if xdg else Path.home() / ".config" / "autostart"
    return root / "rmon.desktop"


def is_autostart_enabled() -> bool:
    return _autostart_desktop_path().exists()


def set_autostart_enabled(enabled: bool) -> None:
    """Turn login-autostart on/off by placing/removing one desktop file.

    Reuses the same .desktop entry shipped for the app menu (see
    data/rmon.desktop / `desktop:` in snapcraft.yaml) rather than
    hand-building another one in Python.
    """
    target = _autostart_desktop_path()
    if enabled:
        target.parent.mkdir(parents=True, exist_ok=True)
        source = _data_dir() / "rmon.desktop"
        try:
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
    else:
        target.unlink(missing_ok=True)


@dataclass
class Config:
    """Small JSON-backed settings store; failure to load/save is non-fatal.

    Only the fields declared here are persisted (`path` is a plain
    attribute set in __post_init__, not a dataclass field, so
    `dataclasses.asdict` naturally excludes it from `save()`).
    """

    interval: int = DEFAULT_INTERVAL
    show_cpu: bool = True
    show_mem: bool = True
    show_swap: bool = True
    show_per_core_in_menu: bool = True

    def __post_init__(self) -> None:
        self.path = _config_path()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        # Each field needs its own coercion (int+clamp vs. bool), so
        # this part stays spelled out rather than looped generically.
        self.interval = max(
            MIN_INTERVAL, min(MAX_INTERVAL, int(data.get("interval", self.interval)))
        )
        self.show_cpu = bool(data.get("show_cpu", self.show_cpu))
        self.show_mem = bool(data.get("show_mem", self.show_mem))
        self.show_swap = bool(data.get("show_swap", self.show_swap))
        self.show_per_core_in_menu = bool(
            data.get("show_per_core_in_menu", self.show_per_core_in_menu)
        )

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass


class RmonApp:
    def __init__(self) -> None:
        self.config = Config()
        self.cpu_monitor = stats.CpuMonitor()
        self._label_guide_cache = self._compute_label_guide()

        icon_dir = _data_dir() / "icons"
        self.indicator = AppIndicator3.Indicator.new(
            APP_ID, "rmon-symbolic", AppIndicator3.IndicatorCategory.SYSTEM_SERVICES
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_icon_theme_path(str(icon_dir))
        self.indicator.set_icon_full("rmon-symbolic", APP_NAME)
        self.indicator.set_title("rmon")

        self.menu = Gtk.Menu()
        self.indicator.set_menu(self.menu)
        # None here (rather than a bool) guarantees the first _update_menu()
        # call sees a mismatch against self.config and builds the menu.
        self._menu_shows_cores: bool | None = None
        self._core_items: list[Gtk.MenuItem] = []

        self._timeout_id: int | None = None
        self._tick()  # populate immediately instead of waiting one interval
        self._schedule()

    # -- polling -----------------------------------------------------

    def _schedule(self) -> None:
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
        self._timeout_id = GLib.timeout_add_seconds(self.config.interval, self._tick)

    def _tick(self) -> bool:
        cpu = self.cpu_monitor.poll()
        mem, swap = stats.read_mem_swap()

        self.indicator.set_label(self._label_text(cpu, mem, swap), self._label_guide_cache)
        self._update_menu(cpu, mem, swap)
        return True  # keep the GLib timeout alive

    def _format_label(self, cpu_part: str, mem_part: str, swap_part: str) -> str:
        parts = []
        if self.config.show_cpu:
            parts.append(cpu_part)
        if self.config.show_mem:
            parts.append(mem_part)
        if self.config.show_swap:
            parts.append(swap_part)
        return "  ".join(parts) if parts else APP_NAME

    def _label_text(self, cpu: stats.CpuUsage, mem: stats.MemUsage, swap: stats.SwapUsage) -> str:
        return self._format_label(
            f"CPU {cpu.overall:0.0f}%", f"MEM {mem.percent:0.0f}%", f"SWAP {swap.percent:0.0f}%"
        )

    def _compute_label_guide(self) -> str:
        """Widest string we expect, so the indicator reserves stable width."""
        return self._format_label("CPU 100%", "MEM 100%", "SWAP 100%")

    # -- menu ----------------------------------------------------------
    #
    # The menu's *structure* (item count/order) only changes when the
    # "show per-core detail" preference or the core count itself
    # changes -- both rare, user-driven events. Rebuilding every
    # widget from scratch on every poll tick would mean tearing down
    # and reallocating the whole GTK menu (plus reconnecting signal
    # handlers on the static items) every 1-30s forever for no reason,
    # so the common path just updates the text of cached item handles.

    @staticmethod
    def _mem_text(mem: stats.MemUsage) -> str:
        return (
            f"Memory: {stats.humanize_kib(mem.used_kib)} / "
            f"{stats.humanize_kib(mem.total_kib)} ({mem.percent:0.0f}%)"
        )

    @staticmethod
    def _swap_text(swap: stats.SwapUsage) -> str:
        return (
            f"Swap: {stats.humanize_kib(swap.used_kib)} / "
            f"{stats.humanize_kib(swap.total_kib)} ({swap.percent:0.0f}%)"
        )

    def _update_menu(self, cpu: stats.CpuUsage, mem: stats.MemUsage, swap: stats.SwapUsage) -> None:
        needs_rebuild = self._menu_shows_cores != self.config.show_per_core_in_menu or (
            self.config.show_per_core_in_menu and len(cpu.per_core) != len(self._core_items)
        )
        if needs_rebuild:
            self._build_menu(cpu, mem, swap)
            return

        self._cpu_item.set_label(f"CPU (overall): {cpu.overall:0.0f}%")
        for idx, (item, pct) in enumerate(zip(self._core_items, cpu.per_core)):
            item.set_label(f"   core {idx}: {pct:0.0f}%")
        self._mem_item.set_label(self._mem_text(mem))
        self._swap_item.set_label(self._swap_text(swap))

    def _build_menu(self, cpu: stats.CpuUsage, mem: stats.MemUsage, swap: stats.SwapUsage) -> None:
        for child in self.menu.get_children():
            self.menu.remove(child)

        self._cpu_item = self._add_static_item(f"CPU (overall): {cpu.overall:0.0f}%")

        self._menu_shows_cores = self.config.show_per_core_in_menu
        self._core_items = []
        if self._menu_shows_cores:
            for idx, pct in enumerate(cpu.per_core):
                self._core_items.append(self._add_static_item(f"   core {idx}: {pct:0.0f}%"))

        self.menu.append(Gtk.SeparatorMenuItem())
        self._mem_item = self._add_static_item(self._mem_text(mem))
        self._swap_item = self._add_static_item(self._swap_text(swap))

        self.menu.append(Gtk.SeparatorMenuItem())
        self._add_action_item("Preferences…", self._on_preferences)
        self._add_action_item("About rmon", self._on_about)
        self.menu.append(Gtk.SeparatorMenuItem())
        self._add_action_item("Quit", self._on_quit)

        self.menu.show_all()

    def _add_static_item(self, text: str) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label=text)
        item.set_sensitive(False)
        self.menu.append(item)
        return item

    def _add_action_item(self, text: str, callback) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label=text)
        item.connect("activate", callback)
        self.menu.append(item)
        return item

    # -- dialogs ---------------------------------------------------------

    def _on_preferences(self, _widget: Gtk.MenuItem) -> None:
        dialog = Gtk.Dialog(title="rmon preferences")
        dialog.set_resizable(False)
        dialog.add_buttons("_Cancel", Gtk.ResponseType.CANCEL, "_OK", Gtk.ResponseType.OK)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        interval_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        interval_row.pack_start(Gtk.Label(label="Refresh every (seconds):"), False, False, 0)
        adjustment = Gtk.Adjustment(
            value=self.config.interval,
            lower=MIN_INTERVAL,
            upper=MAX_INTERVAL,
            step_increment=1,
        )
        spin = Gtk.SpinButton(adjustment=adjustment, climb_rate=1, digits=0)
        interval_row.pack_start(spin, False, False, 0)
        box.add(interval_row)

        cpu_check = Gtk.CheckButton(label="Show CPU in top bar")
        cpu_check.set_active(self.config.show_cpu)
        box.add(cpu_check)

        mem_check = Gtk.CheckButton(label="Show memory in top bar")
        mem_check.set_active(self.config.show_mem)
        box.add(mem_check)

        swap_check = Gtk.CheckButton(label="Show swap in top bar")
        swap_check.set_active(self.config.show_swap)
        box.add(swap_check)

        cores_check = Gtk.CheckButton(label="Show per-core detail in the dropdown")
        cores_check.set_active(self.config.show_per_core_in_menu)
        box.add(cores_check)

        autostart_check = Gtk.CheckButton(label="Start rmon automatically at login")
        autostart_check.set_active(is_autostart_enabled())
        box.add(autostart_check)

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.config.interval = int(spin.get_value())
            self.config.show_cpu = cpu_check.get_active()
            self.config.show_mem = mem_check.get_active()
            self.config.show_swap = swap_check.get_active()
            self.config.show_per_core_in_menu = cores_check.get_active()
            self.config.save()
            set_autostart_enabled(autostart_check.get_active())
            self._label_guide_cache = self._compute_label_guide()
            self._schedule()
            self._tick()
        dialog.destroy()

    def _on_about(self, _widget: Gtk.MenuItem) -> None:
        dialog = Gtk.AboutDialog()
        dialog.set_program_name(APP_NAME)
        dialog.set_version(__version__)
        dialog.set_comments("Live CPU, memory and swap usage in your top bar.")
        dialog.set_website(PROJECT_URL)
        dialog.set_website_label("Project page")
        dialog.set_authors([AUTHOR])
        dialog.set_copyright("© 2026 Jan Rock")
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.run()
        dialog.destroy()

    def _on_quit(self, _widget: Gtk.MenuItem) -> None:
        Gtk.main_quit()


def main() -> int:
    quit_on_signal = lambda *_: Gtk.main_quit()  # noqa: E731
    signal.signal(signal.SIGINT, quit_on_signal)
    signal.signal(signal.SIGTERM, quit_on_signal)
    RmonApp()
    Gtk.main()
    return 0
