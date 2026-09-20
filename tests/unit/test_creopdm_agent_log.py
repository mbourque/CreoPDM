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
