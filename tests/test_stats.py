"""Unit tests for rmon.stats.

Deliberately gi/GTK-free so these run anywhere with plain Python 3,
including CI containers without a display.
"""
import unittest

from rmon import stats


class HumanizeKibTests(unittest.TestCase):
    def test_kib(self) -> None:
        self.assertEqual(stats.humanize_kib(512), "512 KiB")

    def test_mib(self) -> None:
        self.assertEqual(stats.humanize_kib(2048), "2.0 MiB")

    def test_gib(self) -> None:
        self.assertEqual(stats.humanize_kib(8 * 1024 * 1024), "8.0 GiB")

    def test_zero(self) -> None:
        self.assertEqual(stats.humanize_kib(0), "0 KiB")


class ReadMemSwapTests(unittest.TestCase):
    def test_reads_real_proc_meminfo(self) -> None:
        mem, swap = stats.read_mem_swap()
        self.assertGreater(mem.total_kib, 0)
        self.assertGreaterEqual(mem.used_kib, 0)
        self.assertLessEqual(mem.used_kib, mem.total_kib)
        self.assertGreaterEqual(mem.percent, 0.0)
        self.assertLessEqual(mem.percent, 100.0)

        self.assertGreaterEqual(swap.total_kib, 0)
        self.assertGreaterEqual(swap.used_kib, 0)
        self.assertLessEqual(swap.used_kib, swap.total_kib)
        self.assertGreaterEqual(swap.percent, 0.0)
        self.assertLessEqual(swap.percent, 100.0)


class CpuMonitorTests(unittest.TestCase):
    def test_first_poll_is_bounded(self) -> None:
        monitor = stats.CpuMonitor()
        usage = monitor.poll()
        self.assertGreaterEqual(usage.overall, 0.0)
        self.assertLessEqual(usage.overall, 100.0)
        for pct in usage.per_core:
            self.assertGreaterEqual(pct, 0.0)
            self.assertLessEqual(pct, 100.0)

    def test_reports_one_entry_per_online_core(self) -> None:
        import os

        monitor = stats.CpuMonitor()
        usage = monitor.poll()
        self.assertEqual(len(usage.per_core), os.cpu_count())


if __name__ == "__main__":
    unittest.main()
