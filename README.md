# WUD-Updater

Small shell helpers for applying Docker image updates reported by What's Up Docker (WUD), with optional TrueNAS status checks and Discord release-note notifications.

## What It Does

- WUD calls `/wud/on-update.sh` when an image update is available.
- The WUD-side scripts append pending image targets to `/out/images.todo`.
- The host command `updates` shows pending Docker updates, TrueNAS update status, and active alerts.
- When approved, `docker-update-from-wud` pulls matching Docker Compose services or stacks, recreates them, waits for health, and removes successfully processed lines from the WUD file.

## Layout

```text
bin/
  updates
  docker-update-from-wud
wud/
  on-update.sh
  append-updates.sh
  tag-manager.sh
  lsio-release-embed.sh
  release-notes-to-discord.sh
  upstreams.txt
install.sh
```

## Install

Clone the repo, then run:

```bash
./install.sh
```

The installer creates symlinks for `updates` and `docker-update-from-wud`, makes scripts executable, and links the `wud/` directory for the WUD container. It refuses to replace existing non-symlink targets.

Make sure the install bin directory is on your `PATH`, then run:

```bash
updates
updates --dry-run
updates --yes
```

When pending Docker updates exist, `updates` prompts for `a` to run all entries, `s` to select numbered entries, `x` to exclude numbered entries, or `n` to skip. Selection prompts accept comma-separated numbers and ranges such as `1,3-5`. Unselected entries stay pending unless you choose to remove them before running the selected updates.

## WUD Mounts

Mount the installed WUD scripts and output directory into the WUD container:

```yaml
volumes:
  - ${HOME}/docker/wud/scripts:/wud:ro
  - ${HOME}/docker/wud/out:/out
```

Configure WUD to call:

```text
/wud/on-update.sh
```

## Configuration

`updates` reads optional overrides from the environment or from `$HOME/.config/wud-updater/env`. Start from `template.env` if you want a host-local config file:

```bash
mkdir -p "$HOME/.config/wud-updater"
cp template.env "$HOME/.config/wud-updater/env"
```

Common values:

```bash
DOCKER_BASE="$HOME/docker"
WUD_OUT_FILE="$DOCKER_BASE/wud/out/images.todo"
WUD_UPDATE_MODE="stop"
WUD_MAX_WAIT="180"
WUD_LOCK_TIMEOUT="30"
OUT_UID="1000"
OUT_GID="1000"
```

`OUT_UID` and `OUT_GID` are optional. When host-side updates run through `sudo`, set them to the WUD container user and group, usually `1000:1000`, so rewritten todo files and updater logs remain writable outside the root process. `OUT_GUID` is accepted as an alias for `OUT_GID`.

The WUD todo file should be owned by the WUD user/group and group-writable. WUD-side appends preserve an existing file's owner and mode; when creating the todo file for the first time, they default to mode `0660`.

`WUD_LOCK_TIMEOUT` controls how long WUD-side appends and host-side cleanup wait for the shared todo-file lock. The default is `30` seconds; if a stale `${WUD_OUT_FILE}.lock` directory remains, remove it manually after confirming no update script is running.

For release-note notifications, provide webhook and GitHub token values through the WUD container environment or another host-local secret store. Do not put secrets in this repository.

## Requirements

- Bash for host-side scripts.
- Docker with the Compose plugin on the host.
- Standard shell tools used by the updater: `awk`, `sort`, `sed`, `perl`, `find`, `grep`, `script`, and `mktemp`.
- `jq` and `midclt` are optional for TrueNAS status checks in `updates`.
- `curl` and `jq` are required for release-note helper scripts.

## Maintenance

Update the checkout, rerun the installer, and restart the WUD container so it sees the latest mounted scripts:

```bash
git pull --ff-only
./install.sh
docker compose -f "$HOME/docker/wud/docker-compose.yml" restart
```
