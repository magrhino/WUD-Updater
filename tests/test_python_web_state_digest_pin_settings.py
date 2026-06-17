from __future__ import annotations

from pathlib import Path



from tests.web_test_helpers import (
    _client,
    _csrf_headers,
)


def test_managed_digest_pin_updates_persists_true_and_reloads(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    write_response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "true"}},
        headers=headers,
    )
    reload_response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in reload_response.json()["managed"]}

    assert write_response.status_code == 200
    write_managed = {entry["key"]: entry for entry in write_response.json()["managed"]}
    assert write_managed["digest_pin_updates"]["value"] == "true"
    assert write_managed["digest_pin_updates"]["source"] == "configured"
    assert managed["digest_pin_updates"]["value"] == "true"
    assert managed["digest_pin_updates"]["source"] == "configured"


def test_managed_digest_pin_updates_can_be_reset_to_false(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    initial_response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "true"}},
        headers=headers,
    )
    initial_managed = {
        entry["key"]: entry for entry in initial_response.json()["managed"]
    }

    assert initial_response.status_code == 200
    assert initial_managed["digest_pin_updates"]["value"] == "true"
    assert initial_managed["digest_pin_updates"]["source"] == "configured"

    reset_response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "false"}},
        headers=headers,
    )
    managed = {entry["key"]: entry for entry in reset_response.json()["managed"]}

    assert reset_response.status_code == 200
    assert managed["digest_pin_updates"]["value"] == "false"
    assert managed["digest_pin_updates"]["source"] == "configured"


def test_managed_digest_pin_updates_rejects_invalid_value(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    headers = _csrf_headers(client)

    response = client.post(
        "/api/v1/settings/managed",
        json={"values": {"digest_pin_updates": "maybe"}},
        headers=headers,
    )

    assert response.status_code == 422
    assert "maybe" in response.json()["detail"] or "digest_pin_updates" in response.json()["detail"]


def test_digest_pin_updates_env_false_shows_as_not_editable(
    tmp_path: Path,
) -> None:
    """When WUD_DIGEST_PIN_UPDATES=false is set in env, webui editing is disabled."""
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_DIGEST_PIN_UPDATES": "false",
        },
    )

    settings_response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in settings_response.json()["managed"]}

    assert managed["digest_pin_updates"]["value"] == "false"
    assert managed["digest_pin_updates"]["editable"] is False
    assert "WUD_DIGEST_PIN_UPDATES" in managed["digest_pin_updates"]["disabled_reason"]


def test_updater_settings_entry_includes_digest_pin_updates(
    tmp_path: Path,
) -> None:
    """WUD_DIGEST_PIN_UPDATES should appear in the updater settings section."""
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_DIGEST_PIN_UPDATES": "true",
        },
    )

    response = client.get("/api/v1/settings")
    body = response.json()
    updater = {entry["name"]: entry for entry in body["updater"]}

    assert "WUD_DIGEST_PIN_UPDATES" in updater
    assert updater["WUD_DIGEST_PIN_UPDATES"]["value"] == "true"
    assert updater["WUD_DIGEST_PIN_UPDATES"]["configured"] is True


def test_updater_settings_entry_digest_pin_updates_default_is_false(
    tmp_path: Path,
) -> None:
    """Without WUD_DIGEST_PIN_UPDATES in env, the updater settings entry shows false."""
    client = _client(
        tmp_path,
        {"WUD_WEB_DEV_NO_AUTH": "true"},
    )

    response = client.get("/api/v1/settings")
    body = response.json()
    updater = {entry["name"]: entry for entry in body["updater"]}

    assert "WUD_DIGEST_PIN_UPDATES" in updater
    assert updater["WUD_DIGEST_PIN_UPDATES"]["value"] == "false"
    assert updater["WUD_DIGEST_PIN_UPDATES"]["source"] == "default"
    assert updater["WUD_DIGEST_PIN_UPDATES"]["configured"] is False


def test_managed_digest_pin_default_value_is_false(
    tmp_path: Path,
) -> None:
    """The digest_pin_updates managed setting defaults to false with no config."""
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})

    response = client.get("/api/v1/settings")
    managed = {entry["key"]: entry for entry in response.json()["managed"]}

    assert managed["digest_pin_updates"]["default_value"] == "false"
    assert managed["digest_pin_updates"]["value"] == "false"
    assert managed["digest_pin_updates"]["source"] == "default"
    assert managed["digest_pin_updates"]["allowed_values"] == ["false", "true"]
    assert managed["digest_pin_updates"]["editable"] is True
    assert managed["digest_pin_updates"]["restart_required"] is False
