"""System stat collection for rmon.

Everything is read straight from /proc so the app has no runtime
dependency beyond the Python standard library. This module is pure
stdlib (no gi/GTK imports) on purpose so it can be unit tested without
a display or GObject introspection installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _CpuSample:
    idle: int
    total: int


@dataclass
class CpuUsage:
    overall: float
    per_core: list[float] = field(default_factory=list)


@dataclass
class MemUsage:
    total_kib: int
    used_kib: int
    available_kib: int
    percent: float


@dataclass
class SwapUsage:
    total_kib: int
    used_kib: int
    percent: float


def _read_cpu_samples() -> dict[str, _CpuSample]:
    """Parse /proc/stat into one sample per CPU line ('cpu', 'cpu0', ...).

    Field order per the kernel docs is:
    user nice system idle iowait irq softirq steal guest guest_nice
    We treat idle+iowait as "not busy" and the rest of the fields as
    "busy", which is the conventional approximation used by most
    /proc/stat based usage meters.
    """
    samples: dict[str, _CpuSample] = {}
    with open("/proc/stat", "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("cpu"):
                continue
            parts = line.split()
            name = parts[0]
            if name != "cpu" and not name[3:].isdigit():
                continue
            values = [int(v) for v in parts[1:]]
            if len(values) < 4:
                continue
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            samples[name] = _CpuSample(idle=idle, total=total)
    return samples


class CpuMonitor:
    """Tracks CPU counters between successive polls to compute % usage.

    /proc/stat exposes cumulative jiffy counters since boot, so a
    single reading can't tell you current load -- usage is the delta
    between two samples over the delta of elapsed jiffies.
    """

    def __init__(self) -> None:
        self._previous = _read_cpu_samples()
        self._core_names = self._sorted_core_names(self._previous)

    @staticmethod
    def _sorted_core_names(samples: dict[str, _CpuSample]) -> list[str]:
        return sorted((name for name in samples if name != "cpu"), key=lambda n: int(n[3:]))

    def poll(self) -> CpuUsage:
        current = _read_cpu_samples()
        usages: dict[str, float] = {}
        for name, sample in current.items():
            prev = self._previous.get(name)
            if prev is None:
                usages[name] = 0.0
                continue
            idle_delta = sample.idle - prev.idle
            total_delta = sample.total - prev.total
            if total_delta <= 0:
                usages[name] = 0.0
            else:
                usages[name] = max(
                    0.0, min(100.0, 100.0 * (1 - idle_delta / total_delta))
                )
        self._previous = current

        # Core count is stable for the life of the process outside of
        # (rare) CPU hotplug, so avoid re-sorting the core list on
        # every single poll -- only recompute it when it disagrees
        # with what we last saw.
        if len(current) != len(self._core_names) + 1:
            self._core_names = self._sorted_core_names(current)

        overall = usages.get("cpu", 0.0)
        return CpuUsage(overall=overall, per_core=[usages[n] for n in self._core_names])


_MEMINFO_KEYS = frozenset({"MemTotal", "MemFree", "MemAvailable", "SwapTotal", "SwapFree"})


def _parse_meminfo() -> dict[str, int]:
    """Read only the handful of /proc/meminfo fields we actually use.

    The file has 50+ lines; skipping the ones we don't need (and
    stopping once we've seen them all) avoids doing string work on
    every field on every poll for the sake of five numbers.
    """
    info: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            if key not in _MEMINFO_KEYS:
                continue
            rest = rest.strip()
            if rest.endswith("kB"):
                rest = rest[:-2].strip()
            try:
                info[key] = int(rest)
            except ValueError:
                continue
            if len(info) == len(_MEMINFO_KEYS):
                break
    return info


def read_mem_swap() -> tuple[MemUsage, SwapUsage]:
    """Read /proc/meminfo once and return current memory and swap usage."""
    info = _parse_meminfo()

    total = info.get("MemTotal", 0)
    # MemAvailable (kernel >= 3.14) already accounts for reclaimable
    # caches/buffers and is a much better "how much can I actually use"
    # figure than MemFree.
    available = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(0, total - available)
    mem_percent = (used / total * 100.0) if total else 0.0
    mem = MemUsage(
        total_kib=total, used_kib=used, available_kib=available, percent=mem_percent
    )

    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    swap_percent = (swap_used / swap_total * 100.0) if swap_total else 0.0
    swap = SwapUsage(total_kib=swap_total, used_kib=swap_used, percent=swap_percent)

    return mem, swap


def humanize_kib(value_kib: int) -> str:
    """Format a KiB integer as a human readable size, e.g. '3.2 GiB'."""
    value = float(value_kib)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "KiB" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TiB"
