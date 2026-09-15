from creopdm.main import find_available_port


def test_find_available_port_is_localhost_bindable():
    port = find_available_port("127.0.0.1", 0)
    assert isinstance(port, int)
    assert 0 < port < 65536
