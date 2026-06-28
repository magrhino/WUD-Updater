# Release-Note Notifications

WUDup can post release information to Discord from the WebUI after you preview
selected pending updates or a successful apply run. Legacy WUD shell helpers
remain available for existing callback setups. Webhook and token values must
come from the WUDup/WebUI runtime environment, the WUD container environment
for shell callbacks, or another host-local secret store.

## WebUI Workflow

Release-note notifications default disabled. Enable them from Settings, or set
`WUD_RELEASE_NOTES_ENABLED=true` in the WebUI runtime environment to force the
value and make the Settings toggle read-only. Sending notifications is a WebUI
mutation, so the server must also run with `WUD_WEB_MUTATIONS_ENABLED=true`.

Configure `DISCORD_RELEASES_WEBHOOK` in the WUDup runtime environment, with
`DISCORD_WEBHOOK` accepted as a fallback. Webhook URLs and GitHub tokens are not
editable in the WebUI and are never stored in SQLite.

Use WUD's append-only callback (`/wud/on-update.sh`) or the WUD API pending
source to populate pending updates, then choose **Preview release notes** from
selected pending updates or from a completed apply job. The WebUI sender builds
Discord payloads in Python, previews the notification summary without the webhook
URL, and posts one embed per update in Discord-sized batches. It reads WUD
trigger summaries when WUD API metadata is available, but it does not call WUD
trigger POST endpoints.

If a legacy shell release-note callback is also configured, Discord can receive
duplicate notifications for the same WUD update. Keep only one notification path
enabled unless duplicate posts are intentional.

## Default Callback

`/wud/on-update.sh` always calls `/wud/append-updates.sh` first. When
`update_available=true`, it also calls:

```bash
/wud/release-notes-to-discord.sh "$IMAGE" "$CONTAINER_NAME" "$CURRENT_TAG"
```

That helper is the single shell release-note router for WUD callbacks. It
requires:

| Variable | Purpose |
|---|---|
| `DISCORD_RELEASES_WEBHOOK` | Discord webhook for release-note embeds. |

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
| `DISCORD_RELEASES_WEBHOOK` | empty | Discord webhook for release embeds. |
| `DISCORD_WEBHOOK` | empty | Alternate webhook name. |
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

New configurations should call `/wud/release-notes-to-discord.sh` directly.
The compatibility wrappers delegate to the canonical helper.

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
point at a custom LinuxServer.io upstream map.

## Secrets And Logs

Do not commit webhook URLs, GitHub tokens, or private service URLs. Use
environment variables supplied by WUD, Compose secrets, or host-local config.

The legacy tag manager redacts webhook values when logging helper commands, and
shared HTTP errors do not print webhook URLs. Avoid copying raw environment
dumps into issues or pull requests.
