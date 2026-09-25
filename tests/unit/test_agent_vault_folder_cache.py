from creopdm_agent.server import _project_cache_key


def test_project_cache_key_prefers_vault_folder():
    assert _project_cache_key("uuid-1", "robot-arm") == "robot-arm"
    assert _project_cache_key("uuid-1", "") == "uuid-1"
    assert _project_cache_key("", "My Vault") == "My_Vault"
