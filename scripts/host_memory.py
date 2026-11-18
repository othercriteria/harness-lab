"""Read-only Linux host diagnostics; a used swap slot and a new page-out are different facts."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path


def sample(proc=Path("/proc")):
    memory = dict(
        line.split(":", 1) for line in (proc / "meminfo").read_text().splitlines()
    )
    vm = dict(line.split() for line in (proc / "vmstat").read_text().splitlines())
    pressure = {}
    for line in (proc / "pressure/memory").read_text().splitlines():
        kind, *values = line.split()
        pressure[kind] = int(dict(v.split("=") for v in values)["total"])
    return {
        "monotonic": time.monotonic(),
        "memory_kib": {
            key: int(memory[key].split()[0])
            for key in (
                "MemTotal",
                "MemFree",
                "MemAvailable",
                "SwapTotal",
                "SwapFree",
                "SwapCached",
            )
        },
        "vm": {key: int(vm[key]) for key in ("pswpin", "pswpout", "oom_kill")},
        "pressure_us": pressure,
    }


def top_level_swap(root=Path("/sys/fs/cgroup")):
    """Only immediate children: adding parents and descendants double counts charges."""
    rows = {}
    for child in root.iterdir():
        if child.is_dir():
            try:
                size = int((child / "memory.swap.current").read_text())
            except (FileNotFoundError, PermissionError):
                continue
            if size:
                rows[child.name] = size
    return dict(sorted(rows.items(), key=lambda pair: -pair[1]))


def report(seconds):
    before = sample()
    time.sleep(seconds)
    after = sample()
    elapsed = after["monotonic"] - before["monotonic"]
    delta = {key: value - before["vm"][key] for key, value in after["vm"].items()}
    page = os.sysconf("SC_PAGE_SIZE")
    return {
        "sample_end_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": elapsed,
        "memory_kib": after["memory_kib"],
        "swap_in_mib": delta["pswpin"] * page / 2**20,
        "swap_out_mib": delta["pswpout"] * page / 2**20,
        "memory_stall_percent": {
            k: (v - before["pressure_us"][k]) / (elapsed * 10_000)
            for k, v in after["pressure_us"].items()
        },
        "oom_kills_during_sample": delta["oom_kill"],
        "visible_top_level_swap_bytes": top_level_swap(),
    }
