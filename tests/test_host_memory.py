"""Tests for scripts/host_memory.py using synthetic counters; no live host reads."""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import host_memory

MEMINFO = """\
MemTotal:       16384000 kB
MemFree:         2048000 kB
MemAvailable:    5120000 kB
SwapTotal:       8388608 kB
SwapFree:         131072 kB
SwapCached:        65536 kB
"""

VMSTAT = """\
pswpin 1200
pswpout 3400
oom_kill 2
"""

PRESSURE = """\
some avg10=0.50 avg60=0.25 avg300=0.10 total=1000
full avg10=0.00 avg60=0.00 avg300=0.00 total=0
"""

PAGE_SIZE = 65536  # nontrivial 64 KiB page; report must use it, not 4096


def make_proc(base: Path) -> Path:
    proc = base / "proc"
    (proc / "pressure").mkdir(parents=True)
    (proc / "meminfo").write_text(MEMINFO)
    (proc / "vmstat").write_text(VMSTAT)
    (proc / "pressure" / "memory").write_text(PRESSURE)
    return proc


def fixed_sample(monotonic, pswpin, pswpout, oom_kill, swap_free, some_us, full_us):
    return {
        "monotonic": monotonic,
        "memory_kib": {
            "MemTotal": 16384000,
            "MemFree": 2048000,
            "MemAvailable": 5120000,
            "SwapTotal": 8388608,
            "SwapFree": swap_free,
            "SwapCached": 65536,
        },
        "vm": {"pswpin": pswpin, "pswpout": pswpout, "oom_kill": oom_kill},
        "pressure_us": {"some": some_us, "full": full_us},
    }


class SampleTests(unittest.TestCase):
    def test_sample_parses_synthetic_counters(self):
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            proc = make_proc(Path(tmp))
            result = host_memory.sample(proc)
        self.assertEqual(
            result["memory_kib"],
            {
                "MemTotal": 16384000,
                "MemFree": 2048000,
                "MemAvailable": 5120000,
                "SwapTotal": 8388608,
                "SwapFree": 131072,
                "SwapCached": 65536,
            },
        )
        self.assertEqual(result["vm"], {"pswpin": 1200, "pswpout": 3400, "oom_kill": 2})
        self.assertEqual(result["pressure_us"], {"some": 1000, "full": 0})
        self.assertGreaterEqual(result["monotonic"], started)


class TopLevelSwapTests(unittest.TestCase):
    def test_only_immediate_children_counted_and_sorted_descending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cgroup"
            (root / "a" / "nested").mkdir(parents=True)
            (root / "b").mkdir()
            (root / "zero").mkdir()
            (root / "bare").mkdir()
            (root / "stray").write_text("not a directory")
            (root / "a" / "memory.swap.current").write_text("104857600\n")
            (root / "a" / "nested" / "memory.swap.current").write_text("999999999\n")
            (root / "b" / "memory.swap.current").write_text("52428800\n")
            (root / "zero" / "memory.swap.current").write_text("0\n")
            result = host_memory.top_level_swap(root)
        # Nested cgroup under "a" is not added on top of its parent's charge,
        # zero usage is omitted, and missing files are skipped.
        self.assertEqual(result, {"a": 104857600, "b": 52428800})
        self.assertEqual(list(result), ["a", "b"])


class ReportTests(unittest.TestCase):
    def run_report(self, before, after, top_swap):
        with mock.patch.object(host_memory, "sample", side_effect=[before, after]), \
                mock.patch("time.sleep") as sleep, \
                mock.patch("os.sysconf", return_value=PAGE_SIZE), \
                mock.patch.object(host_memory, "top_level_swap", return_value=top_swap), \
                mock.patch.object(host_memory, "datetime") as fake_dt:
            fake_dt.now.return_value.isoformat.return_value = "2025-06-01T12:00:00+00:00"
            result = host_memory.report(5)
        sleep.assert_called_once_with(5)
        return result

    def test_occupied_swap_with_zero_new_page_outs(self):
        # Swap is heavily occupied (8064 MiB of 8192 MiB used) yet pswpout does
        # not move: a used slot is not a new page-out, so swap_out_mib is 0.0
        # while swap_in_mib reflects 100 pages of 64 KiB each.
        before = fixed_sample(1000.0, 1200, 3400, 2, 8192000, 1000, 0)
        after = fixed_sample(1005.0, 1300, 3400, 4, 131072, 31000, 5000)
        top_swap = {"a": 104857600, "b": 52428800}
        result = self.run_report(before, after, top_swap)
        self.assertEqual(result["elapsed_seconds"], 5.0)
        self.assertEqual(result["swap_in_mib"], 6.25)
        self.assertEqual(result["swap_out_mib"], 0.0)
        self.assertEqual(result["memory_stall_percent"], {"some": 0.6, "full": 0.1})
        self.assertEqual(result["oom_kills_during_sample"], 2)
        # The report carries the latest snapshot, not the earlier one.
        self.assertEqual(result["memory_kib"], after["memory_kib"])
        self.assertEqual(result["memory_kib"]["SwapFree"], 131072)
        self.assertEqual(result["visible_top_level_swap_bytes"], top_swap)
        self.assertEqual(result["sample_end_utc"], "2025-06-01T12:00:00+00:00")

    def test_nonzero_page_out_delta(self):
        # Over a 10 s interval, 500 pages swap in and 1250 pages swap out at a
        # 64 KiB page size, so in and out MiB differ; pressure falls, giving
        # negative stall percentages, and no new OOM kills occur.
        before = fixed_sample(2000.0, 1300, 3400, 4, 131072, 31000, 5000)
        after = fixed_sample(2010.0, 1800, 4650, 4, 98304, 20000, 1000)
        result = self.run_report(before, after, {})
        self.assertEqual(result["elapsed_seconds"], 10.0)
        self.assertEqual(result["swap_in_mib"], 31.25)
        self.assertEqual(result["swap_out_mib"], 78.125)
        self.assertEqual(result["memory_stall_percent"], {"some": -0.11, "full": -0.04})
        self.assertEqual(result["oom_kills_during_sample"], 0)
        self.assertEqual(result["memory_kib"], after["memory_kib"])


if __name__ == "__main__":
    unittest.main()
