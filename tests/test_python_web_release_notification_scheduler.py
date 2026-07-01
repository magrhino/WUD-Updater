from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

from wudup import (
    web_pending_sources,
    web_release_notifications as notifications_module,
    web_scheduler,
)
from wudup.db import open_db

from tests.web_test_helpers import (
    _capture_discord_posts,
    _client,
    _fake_release_refresh,
    _install_wud_api,
    _wud_api_container,
)

_ENV = {
    "WUD_WEB_DEV_NO_AUTH": "true",
    "WUD_WEB_MUTATIONS_ENABLED": "true",
    "WUD_RELEASE_NOTES_ENABLED": "true",
    "DISCORD_WEBHOOK": "https://discord.test/webhook-secret",
}


def _shutdown(client) -> None:
    notifications_module.shutdown_release_notification_scheduler_state(client.app.state)
    web_scheduler.shutdown_auto_update_scheduler_state(client.app.state)


def test_poll_sends_wud_api_notifications_without_trigger_token(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=[_wud_api_container(name="app")],
        triggers={"docker.local.app": (200, [])},
    )
    _fake_release_refresh(monkeypatch)
    posted = _capture_discord_posts(monkeypatch)

    def fail_file_read(_path: Path):
        raise AssertionError("notification poller should not read images.todo")

    monkeypatch.setattr(web_pending_sources, "_read_pending_file", fail_file_read)
    client = _client(tmp_path, {**_ENV, "WUD_PENDING_SOURCE": "file"})
    try:
        response = notifications_module.poll_wud_api_release_notifications(
            client.app.state.web_settings,
        )
    finally:
        _shutdown(client)

    assert response is not None
    assert response.sent is True
    assert response.source.active == "api"
    assert len(posted) == 1
    with open_db(tmp_path / "state" / "wud.sqlite") as conn:
        row = conn.execute(
            """
            SELECT metadata_json
            FROM update_runs
            WHERE mode = 'web-release-notifications'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert row is not None
    metadata = json.loads(row["metadata_json"])
    assert metadata["source"] == notifications_module.SCHEDULER_ACTOR_TYPE
    assert metadata["actor_type"] == notifications_module.SCHEDULER_ACTOR_TYPE


def test_poll_skips_duplicate_notifications(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(
        monkeypatch,
        containers=[_wud_api_container(name="app")],
        triggers={"docker.local.app": (200, [])},
    )
    _fake_release_refresh(monkeypatch)
    posted = _capture_discord_posts(monkeypatch)
    client = _client(tmp_path, _ENV)
    try:
        first = notifications_module.poll_wud_api_release_notifications(
            client.app.state.web_settings,
        )
        second = notifications_module.poll_wud_api_release_notifications(
            client.app.state.web_settings,
        )
    finally:
        _shutdown(client)

    assert first is not None
    assert first.sent is True
    assert second is None
    assert len(posted) == 1


def test_poll_skips_degraded_wud_api_quietly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wud_api(monkeypatch, containers=(500, {}))
    posted = _capture_discord_posts(monkeypatch)

    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("release metadata should not refresh when WUD API is degraded")

    monkeypatch.setattr(notifications_module, "refresh_release_notes", fail_refresh)
    client = _client(tmp_path, _ENV)
    try:
        response = notifications_module.poll_wud_api_release_notifications(
            client.app.state.web_settings,
        )
    finally:
        _shutdown(client)

    assert response is None
    assert posted == []


def test_release_notification_scheduler_waits_before_first_tick(monkeypatch) -> None:
    calls: list[str] = []

    class StopBeforeTick:
        timeout: float | None = None

        def wait(self, timeout: float) -> bool:
            self.timeout = timeout
            return True

    def fake_tick(_settings):
        calls.append("tick")

    stop_event = StopBeforeTick()
    monkeypatch.setattr(
        notifications_module,
        "poll_wud_api_release_notifications",
        fake_tick,
    )
    notifications_module._release_notification_scheduler_loop(
        SimpleNamespace(),
        stop_event,
    )

    assert calls == []
    assert stop_event.timeout == notifications_module.RELEASE_NOTIFICATION_POLL_SECONDS


def test_release_notification_scheduler_logs_unexpected_tick_failure(
    monkeypatch,
    caplog,
) -> None:
    calls: list[str] = []

    class StopAfterTick:
        waits = 0
        timeout: float | None = None

        def wait(self, timeout: float) -> bool:
            self.timeout = timeout
            self.waits += 1
            return self.waits > 1

    def fail_tick(_settings):
        calls.append("tick")
        raise RuntimeError("tick failed")

    stop_event = StopAfterTick()
    monkeypatch.setattr(
        notifications_module,
        "poll_wud_api_release_notifications",
        fail_tick,
    )

    with caplog.at_level(logging.ERROR, logger=notifications_module.LOGGER.name):
        notifications_module._release_notification_scheduler_loop(
            SimpleNamespace(),
            stop_event,
        )

    assert calls == ["tick"]
    assert stop_event.timeout == notifications_module.RELEASE_NOTIFICATION_POLL_SECONDS
    assert "release notification scheduler tick failed" in caplog.text


def test_release_notification_scheduler_starts_only_with_mutations(
    tmp_path: Path,
) -> None:
    read_only = _client(tmp_path, {"WUD_WEB_DEV_NO_AUTH": "true"})
    mutating_root = tmp_path / "mutating"
    mutating_root.mkdir()
    mutating = _client(
        mutating_root,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    try:
        assert read_only.app.state.web_release_notification_thread is None
        assert mutating.app.state.web_release_notification_thread is not None
    finally:
        _shutdown(read_only)
        _shutdown(mutating)


def test_release_notification_scheduler_start_reuses_live_thread(
    tmp_path: Path,
) -> None:
    client = _client(
        tmp_path,
        {
            "WUD_WEB_DEV_NO_AUTH": "true",
            "WUD_WEB_MUTATIONS_ENABLED": "true",
        },
    )
    try:
        settings = client.app.state.web_settings
        initial = client.app.state.web_release_notification_thread
        first = notifications_module.start_release_notification_scheduler(
            client.app,
            settings,
        )
        second = notifications_module.start_release_notification_scheduler(
            client.app,
            settings,
        )

        assert initial is not None
        assert initial.is_alive()
        assert first is initial
        assert second is initial
        assert first is client.app.state.web_release_notification_thread
        assert {thread for thread in (initial, first, second) if thread.is_alive()} == {
            initial
        }
    finally:
        _shutdown(client)
