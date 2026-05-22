# Container Script Sync

Container-first deployments can let the helper image manage the scripts mounted
into the WUD container. This keeps `/wud/on-update.sh` and related helpers in
sync with the image version.

## How It Works

Set `WUD_SYNC_SCRIPTS=true` on the `wud-updater` service. Before running its normal
command, the entrypoint copies packaged scripts from `/app/wud` into
`WUD_SCRIPTS_DIR`, which defaults to `/managed-wud`.

The WUD container should mount the same volume read-only at `/wud`:

```yaml
services:
  wud:
    volumes:
      - wud-scripts:/wud:ro

  wud-updater:
    environment:
      WUD_SYNC_SCRIPTS: "true"
      WUD_SCRIPTS_DIR: /managed-wud
    volumes:
      - wud-scripts:/managed-wud
```

After the first sync, configure WUD to call:

```text
/wud/on-update.sh
```

## Safety Rules

The sync target must resolve to a directory that is separate from:

- `/`
- the application directory
- `DOCKER_BASE`
- the parent directory for `WUD_OUT_FILE`

If the target directory is non-empty and does not contain
`.wud-updater-managed`, sync refuses to continue. This prevents accidentally
cleaning an operator-managed directory.

When sync is allowed, the entrypoint removes the previous managed contents,
copies `/app/wud`, marks `*.sh` files executable, and writes
`.wud-updater-managed`.

## Manual Sync

Run a one-shot sync with:

```bash
docker compose -f docs/examples/docker-compose.example.yml run --rm wud-updater sync-wud-scripts
```

Run this once before relying on `/wud/on-update.sh` in a fresh empty script
volume. During upgrades, recreating `wud-updater` with `WUD_SYNC_SCRIPTS=true`
refreshes the scripts automatically.

For local image development, use
`docs/examples/docker-compose.build.yml` instead of the deployment example.
