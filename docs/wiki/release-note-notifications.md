# Release-Note Notifications

WUD-Updater includes optional helpers that post release information to Discord
when WUD reports an available image update. Webhook and token values must come
from the WUD container environment or another host-local secret store.

## Default Callback

`/wud/on-update.sh` always calls `/wud/append-updates.sh` first. When
`update_available=true`, it also calls:

```bash
/wud/release-notes-to-discord.sh "$IMAGE" "$CONTAINER_NAME" "$CURRENT_TAG"
```

That helper requires:

| Variable | Purpose |
|---|---|
| `DISCORD_RELEASES_WEBHOOK` | Discord webhook for release-note embeds. |

It also expects `docker`, `curl`, and `jq` to be available in the runtime
environment.

The helper tries to discover a GitHub repository from the image's
`org.opencontainers.image.source` label. For common LinuxServer.io image names,
it falls back to `https://github.com/linuxserver/docker-<image>`. If it finds a
GitHub repository, it fetches the latest GitHub Release and posts a Discord
embed. If no source can be found, it posts a minimal update notice.

## Tag Manager Helper

`/wud/tag-manager.sh` is an alternate richer release-note router. Wire WUD to
call it only when you want LinuxServer.io upstream mapping or generic GHCR
release embeds.

Common variables:

| Variable | Default | Purpose |
|---|---|---|
| `DISCORD_WEBHOOK` | empty | Discord webhook for normal release embeds. |
| `ADMIN_WEBHOOK` | `DISCORD_WEBHOOK` | Webhook for missing upstream mapping alerts. |
| `GITHUB_TOKEN` | empty | Optional token for GitHub API rate limits. |
| `UPSTREAM_MAP` | `/wud/upstreams.txt` | LinuxServer.io image to upstream repository map. |
| `LSIO_EMBED` | `/wud/lsio-release-embed.sh` | Embed builder invoked by the router. |
| `LOG_DIR` | `/out` | Directory for `tag-manager.YYYYMMDD.log`. |

For LinuxServer.io images, `tag-manager.sh` maps `linuxserver/docker-xyz` to an
upstream `Owner/Repo` entry in `upstreams.txt`. Missing mappings are sent to
`ADMIN_WEBHOOK` and the embed is skipped.

For GHCR images, it treats the image name as the upstream repository and calls
`lsio-release-embed.sh` in generic mode.

## Secrets And Logs

Do not commit webhook URLs, GitHub tokens, or private service URLs. Use
environment variables supplied by WUD, Compose secrets, or host-local config.

The tag manager redacts webhook values when logging helper commands. Avoid
copying raw environment dumps into issues or pull requests.
