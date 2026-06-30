from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

from wudup import web_release_notifications as notifications_module
from wudup.db import init_db, insert_pending_update, insert_update_run, open_db
from wudup.release_notes import ReleaseNoteInfo as ReleaseNoteData
from wudup.release_notes import ReleaseNoteLink as ReleaseNoteLinkData

from tests.web_test_helpers import (
    _client,
    _csrf_headers,
    _install_wud_api,
    _wud_api_container,
)

_RELEASE_NOTIFICATION_ENV = {
    "WUD_WEB_DEV_NO_AUTH": "true",
    "WUD_WEB_MUTATIONS_ENABLED": "true",
    "WUD_RELEASE_NOTES_ENABLED": "true",
    "DISCORD_RELEASES_WEBHOOK": "https://discord.test/webhook-secret",
}


def _fake_release_refresh(monkeypatch) -> None:
    def fake_refresh_release_notes(
        _conn,
        targets,
        _environ,
        **_kwargs,
    ):
        return [
            ReleaseNoteData(
                line_no=target.line_no,
                status="ready",
                provider="github",
                image_repo="acme/app",
                upstream_repo="acme/app",
                release_tag=target.desired_tag or "2.0.0",
                title="v2.0.0",
                links=[
                    ReleaseNoteLinkData(
                        label="GitHub release",
                        url="https://github.com/acme/app/releases/tag/v2.0.0",
                        kind="github_release",
                    )
                ],
            )
            for target in targets
        ]

    monkeypatch.setattr(
        notifications_module,
        "refresh_release_notes",
        fake_refresh_release_notes,
    )


def _capture_discord_posts(
    monkeypatch,
    *,
    fail_on: int | None = None,
) -> list[tuple[str, object]]:
    posted: list[tuple[str, object]] = []

    def fake_post_discord_payload(webhook_url: str, payload: object) -> None:
        posted.append((webhook_url, payload))
        if fail_on is not None and len(posted) == fail_on:
            raise urllib.error.HTTPError(
                webhook_url,
                500,
                "Discord webhook request failed webhook-secret",
                {},
                None,
            )

    monkeypatch.setattr(
        notifications_module,
        "_post_discord_payload",
        fake_post_discord_payload,
    )
    return posted


def _release_notification_client(tmp_path: Path, monkeypatch):
    _fake_release_refresh(monkeypatch)
    posted = _capture_discord_posts(monkeypatch)
    return _client(tmp_path, _RELEASE_NOTIFICATION_ENV), posted


def _write_pending_lines(tmp_path: Path, lines: list[str]) -> None:
    (tmp_path / "state" / "images.todo").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def test_notification_identity_includes_wud_metadata() -> None:
    target = notifications_module.WudTarget(
        line_no=1,
        raw="ghcr.io/acme/app:1.0.0 tag=2.0.0",
        first="ghcr.io/acme/app:1.0.0",
        key="app",
        repo="ghcr.io/acme/app",
        has_tag=True,
        allow_repo=True,
        digest="",
        desired_tag="2.0.0",
        tag_token="1.0.0",
    )
    note = notifications_module.ReleaseNoteInfo(
        line_no=1,
        status="ready",
        provider="github",
        image_repo="ghcr.io/acme/app",
        upstream_repo="acme/app",
        release_tag="2.0.0",
        title="v2.0.0",
    )
    metadata = SimpleNamespace(
        local_digest="sha256:local",
        remote_tag="2.0.0",
        remote_digest="sha256:remote-a",
        link="https://github.com/acme/app",
        labels={
            "org.opencontainers.image.source": "https://github.com/acme/app",
            "ignored": "not persisted",
        },
    )

    first = notifications_module.web_release_notification_state.notification_identity(
        target,
        note,
        metadata,
    )

    assert first.metadata["metadata"] == {
        "local_digest": "sha256:local",
        "remote_tag": "2.0.0",
        "remote_digest": "sha256:remote-a",
        "link": "https://github.com/acme/app",
        "source_label": "https://github.com/acme/app",
    }

    unresolved_target = notifications_module.WudTarget(
        line_no=1,
        raw="ghcr.io/acme/app:1.0.0",
        first="ghcr.io/acme/app:1.0.0",
        key="app",
        repo="ghcr.io/acme/app",
        has_tag=True,
        allow_repo=True,
        digest="",
        desired_tag="",
        tag_token="1.0.0",
    )
    unresolved_note = note.model_copy(update={"release_tag": ""})
    first_fallback = notifications_module.web_release_notification_state.notification_identity(
        unresolved_target,
        unresolved_note,
        metadata,
    )
    changed_fallback = notifications_module.web_release_notification_state.notification_identity(
        unresolved_target,
        unresolved_note,
        SimpleNamespace(**{**metadata.__dict__, "remote_digest": "sha256:remote-b"}),
    )

    assert first_fallback.notification_key != changed_fallback.notification_key


def test_notification_history_by_key_binds_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "state" / "wud.sqlite"
    hostile_key = "abc') OR 1=1 --"
    with open_db(db_path) as conn:
        init_db(conn)
        with conn:
            for key in (hostile_key, "other-key"):
                notifications_module.web_release_notification_state.upsert_notification_history(
                    conn,
                    identity=notifications_module.web_release_notification_state.NotificationIdentity(
                        notification_key=key,
                        metadata={},
                    ),
                    config=notifications_module.web_release_notification_state.ReleaseNotificationConfig(),
                    status="sent",
                    audit_run_id=1,
                    now="2026-06-01T00:00:00+00:00",
                )

        histories = notifications_module.web_release_notification_state.notification_history_by_key(
            conn,
            {hostile_key},
        )

    assert set(histories) == {hostile_key}


def test_release_notification_preview_includes_wud_triggers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _fake_release_refresh(monkeypatch)
    _install_wud_api(
        monkeypatch,
        containers=[
            _wud_api_container(
                image="ghcr.io/acme/app",
                tag="1.0.0",
                remote_tag="2.0.0",
            )
        ],
        triggers={
            "docker.local.app": (
                200,
                [
                    {
                        "id": "discord.release",
                        "type": "discord",
                        "name": "release",
                        "configuration": {"url": "https://discord.test/secret"},
                    }
                ],
            )
        },
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
            "DISCORD_RELEASES_WEBHOOK": "https://discord.test/webhook-secret",
            "WUD_API_BASE_URL": "https://wud.release-notifications.test:3000",
        },
    )
    (tmp_path / "state" / "images.todo").write_text(
        "ghcr.io/acme/app:1.0.0 tag=2.0.0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["destination"] == {
        "type": "discord",
        "configured": True,
        "source": "DISCORD_RELEASES_WEBHOOK",
    }
    assert body["sendable_count"] == 1
    assert body["items"][0]["triggers"] == [
        {"id": "discord.release", "type": "discord", "name": "release"}
    ]
    assert "webhook-secret" not in response.text
    assert "secret" not in json.dumps(body["items"][0]["triggers"])


def test_notification_items_cache_wud_trigger_lookup_by_container(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_container_triggers(_settings, container_id: str):
        calls.append(container_id)
        return (
            [
                notifications_module.ReleaseNotificationTrigger(
                    id="discord.release",
                    type="discord",
                    name="release",
                )
            ],
            "",
        )

    def target(line_no: int) -> notifications_module._NotificationTarget:
        return notifications_module._NotificationTarget(
            target=notifications_module.WudTarget(
                line_no=line_no,
                raw=f"ghcr.io/acme/app:{line_no}.0.0 tag=2.0.0",
                first=f"ghcr.io/acme/app:{line_no}.0.0",
                key=f"app-{line_no}",
                repo="ghcr.io/acme/app",
                has_tag=True,
                allow_repo=True,
                digest="",
                desired_tag="2.0.0",
                tag_token=f"{line_no}.0.0",
            ),
            service_key=f"app-{line_no}",
            wud_container_id="docker.local.app",
        )

    monkeypatch.setattr(
        notifications_module.web_wud_api,
        "container_triggers",
        fake_container_triggers,
    )
    source = notifications_module._NotificationSource(
        targets=(target(1), target(2)),
        source_file="images.todo",
        source=notifications_module.PendingSourceInfo(),
        wud_api=notifications_module.WudApiStatus(
            state="ready",
            available=True,
            metadata_available=True,
            last_checked_at="2026-06-01T00:00:00Z",
        ),
        metadata_by_line={},
    )
    notes = {
        line_no: notifications_module.ReleaseNoteInfo(
            line_no=line_no,
            status="ready",
            provider="github",
            image_repo="ghcr.io/acme/app",
            upstream_repo="acme/app",
            release_tag="2.0.0",
            title="v2.0.0",
        )
        for line_no in (1, 2)
    }

    items, warnings = notifications_module._notification_items(
        object(),
        source,
        notes,
        config=notifications_module.web_release_notification_state.ReleaseNotificationConfig(),
        resend=False,
    )

    assert calls == ["docker.local.app"]
    assert warnings == []
    assert [item.triggers[0].id for item in items] == [
        "discord.release",
        "discord.release",
    ]


def test_release_notification_preview_degrades_when_wud_triggers_require_auth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _fake_release_refresh(monkeypatch)
    _install_wud_api(
        monkeypatch,
        containers=[
            _wud_api_container(
                image="ghcr.io/acme/app",
                tag="1.0.0",
                remote_tag="2.0.0",
            )
        ],
        triggers={"docker.local.app": (401, {"detail": "secret-token"})},
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
            "WUD_API_BASE_URL": "https://wud.release-notifications.test:3000",
        },
    )
    (tmp_path / "state" / "images.todo").write_text(
        "ghcr.io/acme/app:1.0.0 tag=2.0.0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["triggers"] == []
    assert any("requires authentication" in warning for warning in body["warnings"])
    assert "secret-token" not in response.text


def test_release_notification_send_requires_mutations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _fake_release_refresh(monkeypatch)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
            "DISCORD_RELEASES_WEBHOOK": "https://discord.test/webhook-secret",
        },
    )
    (tmp_path / "state" / "images.todo").write_text(
        "ghcr.io/acme/app:1.0.0 tag=2.0.0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "mutations are disabled"


def test_release_notification_preview_disabled_does_not_refresh_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("release metadata should not refresh when disabled")

    monkeypatch.setattr(notifications_module, "refresh_release_notes", fail_refresh)
    client = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    (tmp_path / "state" / "images.todo").write_text(
        "ghcr.io/acme/app:1.0.0 tag=2.0.0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["count"] == 0
    assert body["wud_api"]["available"] is False
    assert body["source"]["detail"] == "Release-note notifications are disabled."
    assert body["wud_api"]["detail"] == "Release-note notifications are disabled."
    assert body["warnings"] == ["Release-note notifications are disabled."]


def test_release_notification_send_requires_webhook(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("release metadata should not refresh without webhook")

    monkeypatch.setattr(notifications_module, "refresh_release_notes", fail_refresh)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
        },
    )
    (tmp_path / "state" / "images.todo").write_text(
        "ghcr.io/acme/app:1.0.0 tag=2.0.0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Discord release-note webhook is not configured"


def test_release_notification_preview_rejects_duplicate_pending_lines(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("release metadata should not refresh for invalid input")

    monkeypatch.setattr(notifications_module, "refresh_release_notes", fail_refresh)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
        },
    )
    (tmp_path / "state" / "images.todo").write_text(
        "ghcr.io/acme/app:1.0.0 tag=2.0.0\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1, 1]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "line_numbers line 1 was provided more than once"


def test_release_notification_preview_uses_completed_run_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _fake_release_refresh(monkeypatch)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
        },
    )
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=False,
            mode="stop",
            wud_file="/out/images.todo",
            metadata_json='{"source":"test"}',
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=7,
            raw="ghcr.io/acme/app:1.0.0 tag=2.0.0",
            image="ghcr.io/acme/app:1.0.0",
            desired_tag="2.0.0",
            service_key="media/app",
            status="resolved",
            status_reason="updated",
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=8,
            raw="ghcr.io/acme/failed:1.0.0 tag=2.0.0",
            image="ghcr.io/acme/failed:1.0.0",
            desired_tag="2.0.0",
            service_key="media/failed",
            status="failed",
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=10,
            raw="ghcr.io/acme/removed:1.0.0 tag=2.0.0",
            image="ghcr.io/acme/removed:1.0.0",
            desired_tag="2.0.0",
            service_key="media/removed",
            status="resolved",
            status_reason="removed-before-run",
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=11,
            raw="ghcr.io/acme/excluded:1.0.0 tag=2.0.0",
            image="ghcr.io/acme/excluded:1.0.0",
            desired_tag="2.0.0",
            service_key="media/excluded",
            status="resolved",
            status_reason="tag-excluded",
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=9,
            raw="ghcr.io/acme/pending:1.0.0 tag=2.0.0",
            image="ghcr.io/acme/pending:1.0.0",
            desired_tag="2.0.0",
            service_key="media/pending",
            status="pending",
        )

    response = client.post(
        "/api/v1/release-notifications/preview",
        json={"run_id": run_id},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_file"] == f"Run #{run_id}"
    assert [item["line_no"] for item in body["items"]] == [7]
    assert body["items"][0]["service_key"] == "media/app"


def test_release_notification_preview_rejects_non_update_run_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("release metadata should not refresh for non-update runs")

    monkeypatch.setattr(notifications_module, "refresh_release_notes", fail_refresh)
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
        },
    )
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=False,
            mode="web-pending-cleanup",
            wud_file="/out/images.todo",
            metadata_json='{"source":"test"}',
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=7,
            raw="ghcr.io/acme/app:1.0.0 tag=2.0.0",
            image="ghcr.io/acme/app:1.0.0",
            desired_tag="2.0.0",
            service_key="media/app",
            status="resolved",
            status_reason="updated",
        )

    response = client.post(
        "/api/v1/release-notifications/preview",
        json={"run_id": run_id},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "release notifications require a successful update run"
    )


def test_release_notification_preview_and_send_redact_cached_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_refresh_release_notes(
        _conn,
        targets,
        _environ,
        **_kwargs,
    ):
        return [
            ReleaseNoteData(
                line_no=target.line_no,
                status="error",
                provider="github",
                image_repo="acme/app",
                upstream_repo="acme/app",
                error="GitHub lookup failed for https://discord.test/webhook-secret",
            )
            for target in targets
        ]

    monkeypatch.setattr(
        notifications_module,
        "refresh_release_notes",
        fake_refresh_release_notes,
    )
    posted = _capture_discord_posts(monkeypatch)
    client = _client(tmp_path, _RELEASE_NOTIFICATION_ENV)
    _write_pending_lines(tmp_path, ["ghcr.io/acme/app:1.0.0 tag=2.0.0"])

    preview = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=_csrf_headers(client),
    )
    send = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=_csrf_headers(client),
    )

    assert preview.status_code == 200
    assert send.status_code == 200
    assert "Release-note status:" in preview.json()["items"][0]["description"]
    assert "webhook-secret" not in preview.text
    assert "webhook-secret" not in json.dumps([payload for _url, payload in posted])


def test_release_notification_send_posts_discord_payload_and_audits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, posted = _release_notification_client(tmp_path, monkeypatch)
    _write_pending_lines(tmp_path, ["ghcr.io/acme/app:1.0.0 tag=2.0.0"])

    response = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=_csrf_headers(client),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["sent"] is True
    assert body["audit_run_id"]
    assert len(posted) == 1
    assert posted[0][0] == "https://discord.test/webhook-secret"
    assert posted[0][1]["embeds"][0]["title"] == "v2.0.0"
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        run = conn.execute(
            "SELECT * FROM update_runs WHERE id = ?",
            (body["audit_run_id"],),
        ).fetchone()
        event = conn.execute(
            "SELECT * FROM update_events WHERE run_id = ?",
            (body["audit_run_id"],),
        ).fetchone()

    run_metadata = json.loads(run["metadata_json"])
    event_metadata = json.loads(event["metadata_json"])
    assert run["mode"] == "web-release-notifications"
    assert run_metadata["destination"] == {
        "type": "discord",
        "source": "DISCORD_RELEASES_WEBHOOK",
    }
    assert run_metadata["sent_count"] == 1
    assert event_metadata["items"][0]["line_no"] == 1
    serialized = json.dumps({"run": run_metadata, "event": event_metadata})
    assert "webhook-secret" not in serialized


def test_release_notification_send_records_history_and_skips_duplicate_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, posted = _release_notification_client(tmp_path, monkeypatch)
    _write_pending_lines(tmp_path, ["ghcr.io/acme/app:1.0.0 tag=2.0.0"])
    headers = _csrf_headers(client)

    sent = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=headers,
    )
    preview = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=headers,
    )
    duplicate_send = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=headers,
    )

    sent_body = sent.json()
    preview_body = preview.json()
    assert sent.status_code == 200
    assert sent_body["items"][0]["notification_status"] == "new"
    assert sent_body["items"][0]["notification_key"]
    assert preview.status_code == 200
    assert preview_body["sendable_count"] == 0
    assert preview_body["skipped_count"] == 1
    assert preview_body["items"][0]["notification_status"] == "skipped_duplicate"
    assert preview_body["items"][0]["notification_send_count"] == 1
    assert preview_body["items"][0]["skipped_reason"] == "Already sent for this update."
    assert duplicate_send.status_code == 422
    assert len(posted) == 1

    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        history = conn.execute(
            """
            SELECT *
            FROM release_notification_history
            WHERE notification_key = ?
            """,
            (sent_body["items"][0]["notification_key"],),
        ).fetchone()

    assert history["status"] == "sent"
    assert history["send_count"] == 1
    assert history["last_audit_run_id"] == sent_body["audit_run_id"]
    assert "webhook-secret" not in history["metadata_json"]


def test_release_notification_duplicate_key_survives_missing_wud_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _fake_release_refresh(monkeypatch)
    _install_wud_api(
        monkeypatch,
        containers=[
            _wud_api_container(
                image="ghcr.io/acme/app",
                tag="1.0.0",
                remote_tag="2.0.0",
            )
        ],
        triggers={"docker.local.app": (200, [])},
    )
    monkeypatch.setattr(
        notifications_module,
        "_post_discord_payload",
        lambda _url, _payload: None,
    )
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
            "WUD_RELEASE_NOTES_ENABLED": "true",
            "DISCORD_RELEASES_WEBHOOK": "https://discord.test/webhook-secret",
            "WUD_API_BASE_URL": "https://wud.release-notifications.test:3000",
        },
    )
    raw = "ghcr.io/acme/app:1.0.0 tag=2.0.0"
    (tmp_path / "state" / "images.todo").write_text(f"{raw}\n", encoding="utf-8")
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        init_db(conn)
        run_id = insert_update_run(
            conn,
            started_at="2026-05-27T12:00:00+00:00",
            status="success",
            dry_run=False,
            mode="stop",
            wud_file="/out/images.todo",
        )
        insert_pending_update(
            conn,
            run_id=run_id,
            line_no=1,
            raw=raw,
            image="ghcr.io/acme/app:1.0.0",
            desired_tag="2.0.0",
            service_key="media/app",
            status="resolved",
            status_reason="updated",
        )
    headers = _csrf_headers(client)

    sent = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=headers,
    )
    run_preview = client.post(
        "/api/v1/release-notifications/preview",
        json={"run_id": run_id},
        headers=headers,
    )

    assert sent.status_code == 200
    assert run_preview.status_code == 200
    assert run_preview.json()["sendable_count"] == 0
    assert run_preview.json()["items"][0]["notification_key"] == sent.json()["items"][0][
        "notification_key"
    ]
    assert run_preview.json()["items"][0]["notification_status"] == "skipped_duplicate"


def test_release_notification_remote_change_gets_new_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, _ = _release_notification_client(tmp_path, monkeypatch)
    _write_pending_lines(tmp_path, ["ghcr.io/acme/app:1.0.0 tag=2.0.0"])
    headers = _csrf_headers(client)

    sent = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=headers,
    )
    _write_pending_lines(tmp_path, ["ghcr.io/acme/app:1.0.0 tag=2.1.0"])
    preview = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=headers,
    )

    assert sent.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["sendable_count"] == 1
    assert preview.json()["items"][0]["notification_status"] == "new"
    assert preview.json()["items"][0]["notification_key"] != sent.json()["items"][0][
        "notification_key"
    ]


def test_release_notification_cooldown_policy_allows_after_cooldown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, _ = _release_notification_client(tmp_path, monkeypatch)
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        init_db(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO web_settings (key, value, updated_at)
                VALUES
                    (
                        'release_notifications.resend_policy',
                        'cooldown',
                        '2026-06-01T00:00:00+00:00'
                    ),
                    (
                        'release_notifications.cooldown_seconds',
                        '60',
                        '2026-06-01T00:00:00+00:00'
                    )
                """
            )
    _write_pending_lines(tmp_path, ["ghcr.io/acme/app:1.0.0 tag=2.0.0"])
    headers = _csrf_headers(client)
    sent = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=headers,
    )
    notification_key = sent.json()["items"][0]["notification_key"]

    with open_db(db_path) as conn:
        with conn:
            conn.execute(
                """
                UPDATE release_notification_history
                SET last_sent_at = '2999-01-01T00:00:00+00:00'
                WHERE notification_key = ?
                """,
                (notification_key,),
            )
    blocked = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=headers,
    )
    with open_db(db_path) as conn:
        with conn:
            conn.execute(
                """
                UPDATE release_notification_history
                SET last_sent_at = '2026-01-01T00:00:00+00:00'
                WHERE notification_key = ?
                """,
                (notification_key,),
            )
    allowed = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1]},
        headers=headers,
    )

    assert sent.status_code == 200
    assert blocked.json()["sendable_count"] == 0
    assert blocked.json()["items"][0]["notification_status"] == "skipped_cooldown"
    assert allowed.json()["sendable_count"] == 1
    assert allowed.json()["items"][0]["notification_status"] == "cooldown_ready"


def test_release_notification_manual_resend_increments_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, _ = _release_notification_client(tmp_path, monkeypatch)
    _write_pending_lines(tmp_path, ["ghcr.io/acme/app:1.0.0 tag=2.0.0"])
    headers = _csrf_headers(client)
    first = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "confirmation": "send-release-notes"},
        headers=headers,
    )
    preview = client.post(
        "/api/v1/release-notifications/preview",
        json={"line_numbers": [1], "resend": True},
        headers=headers,
    )
    second = client.post(
        "/api/v1/release-notifications/send",
        json={"line_numbers": [1], "resend": True, "confirmation": "send-release-notes"},
        headers=headers,
    )

    assert first.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["sendable_count"] == 1
    assert preview.json()["items"][0]["notification_status"] == "manual_resend"
    assert second.status_code == 200
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        history = conn.execute(
            """
            SELECT send_count
            FROM release_notification_history
            WHERE notification_key = ?
            """,
            (first.json()["items"][0]["notification_key"],),
        ).fetchone()
    assert history["send_count"] == 2


def test_release_notification_send_batches_discord_embeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client, posted = _release_notification_client(tmp_path, monkeypatch)
    lines = [
        f"ghcr.io/acme/app{i}:1.0.0 tag=2.0.0"
        for i in range(1, 12)
    ]
    _write_pending_lines(tmp_path, lines)

    response = client.post(
        "/api/v1/release-notifications/send",
        json={
            "line_numbers": list(range(1, 12)),
            "confirmation": "send-release-notes",
        },
        headers=_csrf_headers(client),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["sendable_count"] == 11
    assert body["batch_count"] == 2
    assert [len(payload["embeds"]) for _url, payload in posted] == [10, 1]


def test_release_notification_send_audits_partial_discord_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _fake_release_refresh(monkeypatch)
    posted = _capture_discord_posts(monkeypatch, fail_on=2)
    client = _client(tmp_path, _RELEASE_NOTIFICATION_ENV)
    lines = [
        f"ghcr.io/acme/app{i}:1.0.0 tag=2.0.0"
        for i in range(1, 12)
    ]
    _write_pending_lines(tmp_path, lines)

    response = client.post(
        "/api/v1/release-notifications/send",
        json={
            "line_numbers": list(range(1, 12)),
            "confirmation": "send-release-notes",
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 500
    assert len(posted) == 2
    assert "webhook-secret" not in response.text
    db_path = tmp_path / "state" / "wud.sqlite"
    with open_db(db_path) as conn:
        run = conn.execute(
            """
            SELECT *
            FROM update_runs
            WHERE mode = 'web-release-notifications'
            """,
        ).fetchone()
        event = conn.execute(
            "SELECT * FROM update_events WHERE run_id = ?",
            (run["id"],),
        ).fetchone()
        history_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM release_notification_history
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        history_metadata = [
            row["metadata_json"]
            for row in conn.execute("SELECT metadata_json FROM release_notification_history")
        ]

    run_metadata = json.loads(run["metadata_json"])
    event_metadata = json.loads(event["metadata_json"])
    assert run["status"] == "failure"
    assert event["status"] == "failure"
    assert run_metadata["sent_count"] == 10
    assert run_metadata["sent_batch_count"] == 1
    assert run_metadata["batch_count"] == 2
    assert event_metadata["items"][0]["line_no"] == 1
    assert [(row["status"], row["count"]) for row in history_rows] == [
        ("failure", 1),
        ("sent", 10),
    ]
    serialized = json.dumps({"run": run_metadata, "event": event_metadata})
    assert "webhook-secret" not in serialized
    assert "webhook-secret" not in json.dumps(history_metadata)
