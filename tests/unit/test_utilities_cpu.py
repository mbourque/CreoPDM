"""Utilities → Health CPU load probe."""

from __future__ import annotations

from creopdm.services.utilities_service import (
    _cpu_status_for_percent,
    collect_cpu_usage,
)


def test_cpu_status_thresholds():
    assert _cpu_status_for_percent(None) == "ok"
    assert _cpu_status_for_percent(12.0) == "ok"
    assert _cpu_status_for_percent(70.0) == "busy"
    assert _cpu_status_for_percent(89.9) == "busy"
    assert _cpu_status_for_percent(90.0) == "hot"


def test_collect_cpu_usage_reports_percent_or_load():
    """Host probe should return a usable percent and/or load average on CI hosts."""
    cpu = collect_cpu_usage()
    assert cpu.logical_cpus is None or cpu.logical_cpus >= 1
    if cpu.percent is not None:
        assert 0.0 <= cpu.percent <= 100.0
        assert cpu.percent_label.endswith("%")
        assert cpu.status in {"ok", "busy", "hot"}
    else:
        # Some hosts may only expose load average (or neither in odd environments).
        assert cpu.load_1 is not None or cpu.error
