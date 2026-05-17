# WUD-Updater

Updating Docker images using WUD's notification system, with host-side update
helpers and container scripts for a TrueNAS Docker host.

## Layout

```text
bin/
  docker-update-from-wud
  updates
wud/
  append-updates.sh
  on-update.sh
  tag-manager.sh
  lsio-release-embed.sh
  release-notes-to-discord.sh
  upstreams.txt
install.sh
```

`bin/updates` is the command to call from your shell. It displays pending WUD
Docker updates, TrueNAS system update status, and active TrueNAS alerts. When
Docker updates are pending it prompts before running `bin/docker-update-from-wud`.

`wud/` is the container-facing script directory. Mount it into WUD at `/wud`.

## Install On TrueNAS

Clone the repository to a persistent host path:

```bash
git clone git@github.com:magrhino/WUD-Updater.git ~/src/WUD-Updater
~/src/WUD-Updater/install.sh
```

Make sure `~/bin` is on your `PATH`:

```bash
export PATH="$HOME/bin:$PATH"
```

Then your shell can call:

```bash
updates
updates --dry-run
updates -y
```

## WUD Compose Mounts

Use the symlink created by `install.sh`:

```yaml
volumes:
  - ${HOME}/docker/wud/scripts:/wud:ro
  - ${HOME}/docker/wud/out:/out
```

The scripts inside the WUD container continue to use `/wud/...` and `/out/...`.

## Optional Host Config

You can override defaults with environment variables or with:

```text
~/.config/wud-updater/env
```

Supported values:

```bash
DOCKER_BASE="$HOME/docker"
WUD_OUT_FILE="$DOCKER_BASE/wud/out/images.todo"
WUD_UPDATE_MODE="stop"
WUD_MAX_WAIT="180"
```

Secrets such as Discord webhooks and GitHub tokens should stay out of this repo.
Pass them through your compose environment or another host-local secret store.

## Updating

```bash
git -C ~/src/WUD-Updater pull --ff-only
~/src/WUD-Updater/install.sh
docker compose -f ~/docker/wud/docker-compose.yml restart
```
