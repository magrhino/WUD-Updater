# Container Script Sync

Container-first deployments can let the helper image manage the scripts mounted
into the WUD container. This keeps `/wud/append-updates.sh`,
`/wud/on-update.sh`, and related helpers in sync with the image version.

## How It Works

Before running its normal command, the entrypoint copies packaged scripts from
`/app/wud` into the managed scripts directory when that directory exists and is
writable. The destination defaults to `/managed-wud`, so the common Compose
mount is enough to enable automatic sync.

The WUD container should mount the same volume read-only at `/wud`:

```yaml
services:
  wud:
    volumes:
      - wud-scripts:/wud:ro

  wudup:
    volumes:
      - wud-scripts:/managed-wud
```

Set `WUD_SYNC_SCRIPTS=false` to opt out of startup sync. Set
`WUD_SYNC_SCRIPTS=true` to force sync, including when using a custom
`WUD_SCRIPTS_DIR`. Set `WUDUP_LEGACY_SCRIPTS=false` for API-first WebUI
deployments; that syncs no WUD command scripts instead of refreshing legacy WUD
callbacks. Remove WUD command triggers for `/wud/append-updates.sh`,
`/wud/on-update.sh`, and `/wud/tag-manager.sh`, then recreate the stack before
disabling legacy mode.

After the first sync, configure WUD to call:

```text
/wud/append-updates.sh
```

Use `/wud/on-update.sh` only when you intentionally keep the legacy shell
release-note notification path. WebUI release-note notifications poll WUD's API
directly.

## Safety Rules

The sync target must resolve to a directory that is separate from:

- `/`
- the application directory
- `DOCKER_BASE`
- the parent directory for `WUD_OUT_FILE`

If the target directory is non-empty and does not contain
`.wudup-managed`, sync refuses to continue. This prevents accidentally
cleaning an operator-managed directory.

When sync is allowed, the entrypoint removes the previous managed contents,
copies `/app/wud`, marks `*.sh` files executable, and writes
`.wudup-managed`.

## Manual Sync

Run a one-shot sync with:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wudup sync-wud-scripts
```

Run this once before relying on `/wud/append-updates.sh` when you intentionally
disabled startup sync. During upgrades, recreating `wudup` refreshes the scripts
automatically when the managed script volume is mounted.

For local image development, use
`docs/examples/docker-compose.build.yml` instead of the deployment example.
