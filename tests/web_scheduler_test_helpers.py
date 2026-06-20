
from __future__ import annotations

from datetime import datetime

from wudup import web_scheduler, web_settings


def _auto_update_tick(client, now: datetime):
    return web_scheduler._auto_update_tick(
        client.app,
        client.app.state.web_settings,
        effective_config_loader=web_settings._effective_config,
        now=now,
    )
