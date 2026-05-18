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

## GitHub Release Embed Helper

`/wud/github-release-embed.sh` is the shared release-note embed builder. It can
post any GitHub release directly:

```bash
/wud/github-release-embed.sh --repo Owner/Repo --tag latest --webhook "$DISCORD_WEBHOOK"
```

It also supports LinuxServer.io releases that need an upstream project lookup:

```bash
/wud/github-release-embed.sh --provider lsio --lsio linuxserver/docker-radarr --upstream Radarr/Radarr --webhook "$DISCORD_WEBHOOK"
```

Common variables:

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | empty | Optional token for GitHub API rate limits. |
| `MAX_COMMITS` | `3` | Maximum representative PRs or commits to include. |
| `COLOR_HEX` | `0x57F287` | Discord embed color. |

The default `github` provider fetches GitHub Releases for `--repo Owner/Repo`.
The legacy provider name `generic` is still accepted as an alias.

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
| `RELEASE_EMBED` | `/wud/github-release-embed.sh` | Embed builder invoked by the router. |
| `LOG_DIR` | `/out` | Directory for `tag-manager.YYYYMMDD.log`. |

For LinuxServer.io images, `tag-manager.sh` maps `linuxserver/docker-xyz` to an
upstream `Owner/Repo` entry in `upstreams.txt`. Missing mappings are sent to
`ADMIN_WEBHOOK` and the embed is skipped.

For GHCR images, it treats the image name as the upstream repository and calls
`github-release-embed.sh` in GitHub mode.

## Secrets And Logs

Do not commit webhook URLs, GitHub tokens, or private service URLs. Use
environment variables supplied by WUD, Compose secrets, or host-local config.

The tag manager redacts webhook values when logging helper commands. Avoid
copying raw environment dumps into issues or pull requests.
