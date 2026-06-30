# Release-Note Notifications

WUDup can post release information to Discord from the WebUI after you preview
selected pending updates or a successful apply run. Legacy WUD shell helpers
remain available for existing callback setups. GitHub token values must come
from the WUDup/WebUI runtime environment, the WUD container environment for
shell callbacks, or another host-local secret store. Discord webhooks can come
from those same places or from the WebUI-managed webhook field.

## WebUI Workflow

Release-note notifications default disabled. Enable them from Settings, or set
`WUD_RELEASE_NOTES_ENABLED=true` in the WebUI runtime environment to force the
value and make the Settings toggle read-only. Sending notifications is a WebUI
mutation, so the server must also run with `WUD_WEB_MUTATIONS_ENABLED=true`.

Configure a Discord webhook from Settings, or set `DISCORD_WEBHOOK` in the
WUDup runtime environment. Environment webhooks override and disable the
WebUI-managed webhook field.

Use the WUD API pending source when available, or keep WUD's append-only
callback as fallback/import compatibility. The WebUI sender builds Discord
payloads in Python from the shared pending-line representation, previews the
notification summary without the webhook URL, and posts one embed per update in
Discord-sized batches. It reads WUD trigger summaries when WUD API metadata is
available, but it does not call WUD trigger POST endpoints.

If a legacy shell release-note callback is also configured, Discord can receive
duplicate notifications for the same WUD update. Keep only one notification path
enabled unless duplicate posts are intentional.

Example Discord notification:

```text
Release notes ready

radarr
linuxserver/radarr:5.21.1 -> linuxserver/radarr:5.22.0

Release: v5.22.0.9716
Source: https://github.com/Radarr/Radarr/releases/tag/v5.22.0.9716

Highlights
- Fixed manual import parsing for nested folders.
- Updated translation files.
- Improved health check messaging.
```

With summary verbosity, WUDup keeps the message to the release summary and
links. With full verbosity, the release body is appended and truncated to
Discord's embed limits.

## Legacy Shell Callback

`/wud/on-update.sh` remains available for existing shell-notification
deployments. It always calls `/wud/append-updates.sh` first. When
`update_available=true`, it also calls:

```bash
/wud/release-notes-to-discord.sh "$IMAGE" "$CONTAINER_NAME" "$CURRENT_TAG"
```

That helper is the single shell release-note router for WUD callbacks. It
requires:

| Variable | Purpose |
|---|---|
| `DISCORD_WEBHOOK` | Discord webhook for release-note embeds. |

It also expects `docker`, `curl`, and `jq` to be available in the runtime
environment.

The helper tries to discover a GitHub repository from the image's
`org.opencontainers.image.source` label. It also handles fully qualified GitHub
Container Registry references that start with `ghcr.io/`, and LinuxServer.io
images through the legacy `linuxserver/docker-<image>` GitHub release fallback.
If no source can be found, it posts a minimal update notice.

## Direct Shell Use

The same canonical helper can post a GitHub release directly:

```bash
/wud/release-notes-to-discord.sh --repo Owner/Repo --tag latest --webhook "$DISCORD_WEBHOOK"
```

It also supports LinuxServer.io releases that need an upstream project lookup:

```bash
/wud/release-notes-to-discord.sh --provider lsio --lsio linuxserver/docker-radarr --upstream Radarr/Radarr --webhook "$DISCORD_WEBHOOK"
```

Common variables:

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_WEBHOOK` | empty | Discord webhook for release embeds. |
| `ADMIN_WEBHOOK` | selected release webhook | Webhook for missing upstream mapping alerts. |
| `GITHUB_TOKEN` | empty | Optional token for GitHub API rate limits. |
| `MAX_COMMITS` | `3` | Maximum representative PRs or commits to include. |
| `COLOR_HEX` | `0x57F287` | Discord embed color. |
| `UPSTREAM_MAP` | `/wud/upstreams.txt` | LinuxServer.io image to upstream repository map used by explicit LSIO mode and `tag-manager.sh`. |
| `RELEASE_EMBED` | `/wud/github-release-embed.sh` | Compatibility hook used by `tag-manager.sh`. |
| `LOG_DIR` | `/out` | Compatibility log directory used by `tag-manager.sh`. |

The default `github` provider fetches GitHub Releases for `--repo Owner/Repo`.
The legacy provider name `generic` is still accepted as an alias.

Compatibility entrypoints remain available for existing WUD configurations:

```bash
/wud/github-release-embed.sh --repo Owner/Repo --webhook "$DISCORD_WEBHOOK"
/wud/tag-manager.sh
```

New WebUI-focused configurations should not use these shell notification
wrappers. Keep them only for existing WUD callback setups that intentionally
send release notes outside the WebUI.

## LinuxServer.io Mapping

For default WUD callbacks, LinuxServer.io images keep the legacy behavior:
`linuxserver/xyz` resolves to the GitHub repository
`linuxserver/docker-xyz`.

For explicit LSIO mode or existing `tag-manager.sh` configurations,
`linuxserver/docker-xyz` maps to an upstream `Owner/Repo` entry in
`upstreams.txt`. Missing mappings are sent to `ADMIN_WEBHOOK` and the embed is
skipped.

Explicit LSIO embeds include both the LinuxServer.io release link and the
upstream release or project link.

## WebUI Release Links

The WebUI uses a separate Python service for structured release-note metadata.
It does not call the shell helper or parse Discord embeds. The WebUI cache uses
the same `GITHUB_TOKEN` for rate limits and can use `WUD_WEB_UPSTREAM_MAP` to
point at a custom LinuxServer.io upstream map. WebUI-sent Discord notifications
use `DISCORD_WEBHOOK` first. When it is not set, the Settings page can save a
Discord webhook URL in SQLite. Settings responses only report whether that
stored webhook is configured; the raw URL is not returned to the browser.

## Secrets And Logs

Do not commit webhook URLs, GitHub tokens, or private service URLs. Use
environment variables supplied by WUD, Compose secrets, host-local config, or
the WebUI-managed webhook field. Treat the WebUI SQLite database as
secret-bearing if you store a webhook there.

The legacy tag manager redacts webhook values when logging helper commands, and
shared HTTP errors do not print webhook URLs. WebUI Settings responses, audit
records, support bundles, and send errors also redact webhook values. Avoid
copying raw environment dumps or SQLite rows into issues or pull requests.
