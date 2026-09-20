from pathlib import Path

from creopdm_agent.logbuf import LogBuffer, install_log_buffer
import logging


def test_log_buffer_keeps_recent_lines():
    buf = LogBuffer(capacity=3)
    buf.append("one")
    buf.append("two")
    buf.append("three")
    buf.append("four")
    generation, lines = buf.snapshot()
    assert generation >= 4
    assert lines == ["two", "three", "four"]


def test_install_log_buffer_captures_logger():
    buf = LogBuffer()
    install_log_buffer(buf)
    logging.getLogger("creopdm_agent").info("hello-tray-log")
    _, lines = buf.snapshot()
    assert any("hello-tray-log" in line for line in lines)
    assert any("Log capture ready" in line or "log started" in line.lower() for line in lines)


def test_log_buffer_writes_file(tmp_path):
    path = tmp_path / "agent.log"
    buf = LogBuffer(log_path=path)
    buf.append("line-one")
    assert "line-one" in path.read_text(encoding="utf-8")


def test_uvicorn_log_config_points_at_buffer_handler():
    from creopdm_agent.logbuf import uvicorn_log_config

    cfg = uvicorn_log_config()
    assert cfg["handlers"]["default"]["class"] == "creopdm_agent.logbuf.BufferHandler"
    assert "uvicorn.access" in cfg["loggers"]


def test_winforms_script_includes_path_and_title(tmp_path):
    from creopdm_agent.logui import _winforms_script

    log_path = tmp_path / "agent.log"
    log_path.write_text("", encoding="utf-8")
    script = _winforms_script(log_path, "CreoPDM agent log")
    assert "agent.log" in script
    assert "CreoPDM agent log" in script
    assert "System.Windows.Forms" in script
