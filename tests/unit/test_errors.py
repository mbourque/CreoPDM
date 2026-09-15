from creopdm.constants import APP_NAME


def test_unknown_project_error_envelope(client):
    response = client.get("/api/projects/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "PROJECT_NOT_FOUND"
    assert "message" in payload["error"]
    assert payload["error"]["details"]["uuid"] == "00000000-0000-0000-0000-000000000000"
    assert APP_NAME not in payload["error"]["code"]


def test_validation_error_envelope_is_json(client):
    response = client.post("/api/projects", json={"name": ""})
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(payload["error"]["details"]["errors"], list)
