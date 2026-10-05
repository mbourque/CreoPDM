"""Utilities → Health I/O wait, disk, and network throughput probe."""

from __future__ import annotations

import sys

from creopdm.services.utilities_service import (
    _format_bytes_per_sec,
    _io_status_for_iowait,
    _rate_from_counters,
    collect_io_usage,
)


def test_io_status_thresholds():
    assert _io_status_for_iowait(None) == "ok"
    assert _io_status_for_iowait(5.0) == "ok"
    assert _io_status_for_iowait(20.0) == "busy"
    assert _io_status_for_iowait(39.9) == "busy"
    assert _io_status_for_iowait(40.0) == "hot"


def test_format_bytes_per_sec():
    assert _format_bytes_per_sec(None) == "—"
    assert _format_bytes_per_sec(500) == "500 B/s"
    assert _format_bytes_per_sec(2048).endswith("/s")


def test_rate_from_counters():
    assert _rate_from_counters(None, (1, 1), elapsed=0.2) == (None, None)
    rx, tx = _rate_from_counters((100, 200), (300, 600), elapsed=0.2, scale=1)
    assert rx == 1000
    assert tx == 2000


def test_collect_io_usage_reports_rates_or_note():
    """Host probe should return I/O wait and/or disk/network rates, or a clear note."""
    io = collect_io_usage()
    assert io.status in {"ok", "busy", "hot"}
    assert io.iowait_label
    assert io.read_label
    assert io.write_label
    assert io.net_rx_label
    assert io.net_tx_label
    if io.iowait_percent is not None:
        assert 0.0 <= io.iowait_percent <= 100.0
        assert io.iowait_label.endswith("%")
    if io.read_bytes_per_sec is not None:
        assert io.read_bytes_per_sec >= 0
        assert io.read_label.endswith("/s")
    if io.write_bytes_per_sec is not None:
        assert io.write_bytes_per_sec >= 0
        assert io.write_label.endswith("/s")
    if io.net_rx_bytes_per_sec is not None:
        assert io.net_rx_bytes_per_sec >= 0
        assert io.net_rx_label.endswith("/s")
    if io.net_tx_bytes_per_sec is not None:
        assert io.net_tx_bytes_per_sec >= 0
        assert io.net_tx_label.endswith("/s")
    if (
        io.iowait_percent is None
        and io.read_bytes_per_sec is None
        and io.write_bytes_per_sec is None
        and io.net_rx_bytes_per_sec is None
        and io.net_tx_bytes_per_sec is None
    ):
        assert io.error
    if sys.platform == "win32" and (
        io.read_bytes_per_sec is not None
        or io.write_bytes_per_sec is not None
        or io.net_rx_bytes_per_sec is not None
        or io.net_tx_bytes_per_sec is not None
    ):
        assert io.iowait_percent is None
        assert io.error and "Linux" in io.error
