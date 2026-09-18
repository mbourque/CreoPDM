from creopdm.exceptions import ConfigurationError
from creopdm.main import find_available_port, lan_addresses, lan_firewall_hint


def test_find_available_port_is_localhost_bindable():
    port = find_available_port("127.0.0.1", 0)
    assert isinstance(port, int)
    assert 0 < port < 65536


def test_find_available_port_binds_all_interfaces():
    port = find_available_port("0.0.0.0", 0)
    assert isinstance(port, int)
    assert 0 < port < 65536


def test_lan_addresses_are_ipv4_strings():
    for address in lan_addresses():
        parts = address.split(".")
        assert len(parts) == 4
        assert not address.startswith("127.")


def test_lan_firewall_hint_is_linux_only(monkeypatch):
    monkeypatch.setattr("creopdm.main.os.name", "posix")
    hint = lan_firewall_hint(52113)
    assert hint is not None
    assert "52113" in hint
    assert "ufw allow 52113/tcp" in hint
    monkeypatch.setattr("creopdm.main.os.name", "nt")
    assert lan_firewall_hint(52113) is None


def test_find_available_port_keeps_the_settings_port(monkeypatch):
    def fake_bind(host: str, port: int) -> int:
        assert port == 8765
        return 8765

    monkeypatch.setattr("creopdm.main._bind_port", fake_bind)
    assert find_available_port("0.0.0.0", 8765) == 8765


def test_find_available_port_does_not_replace_a_blocked_settings_port(monkeypatch):
    def fake_bind(host: str, port: int) -> int:
        raise PermissionError(
            10013,
            "An attempt was made to access a socket in a way forbidden by its access permissions",
        )

    monkeypatch.setattr("creopdm.main._bind_port", fake_bind)
    try:
        find_available_port("127.0.0.1", 1111)
    except ConfigurationError as exc:
        assert "1111" in exc.message
        assert "Settings" in exc.message
    else:
        raise AssertionError("expected ConfigurationError")
