from creopdm.main import find_available_port, lan_addresses


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
