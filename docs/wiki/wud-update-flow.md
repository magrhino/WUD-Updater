# WUD Update Flow

WUD-Updater is built around a shared, line-oriented todo file. WUD writes update
events into that file, and the host or helper container later applies selected
entries.

## Callback Flow

1. WUD detects an available image update.
2. WUD calls `/wud/on-update.sh`.
3. `on-update.sh` calls `/wud/append-updates.sh`.
4. `append-updates.sh` appends or replaces one line in `${WUD_OUT_FILE}`.
5. `updates` displays the file and asks whether to run `docker-update-from-wud`.
6. `docker-update-from-wud` discovers Compose projects under `DOCKER_BASE`,
   pulls matching images, recreates matching services or stacks, waits for
   health, and removes successful entries.

The default WUD output path is `/out/images.todo` inside the WUD container. Host
installs commonly map that to `$HOME/docker/wud/out/images.todo`.

## Todo File Format

Blank lines and lines beginning with `#` are ignored. Each actionable line starts
with an image or container target:

```text
repo/app:latest
repo/app@sha256:abc123
repo/app:1.0 tag=2.0
```

Digest-pinned references use the `image@sha256:...` form. The updater validates
that the pulled image resolves to the requested digest before treating the update
as successful.

Tag updates use a `tag=<new-tag>` token after a tagged source image. They stay
pending unless the updater is run with `--allow-tag-updates`.

Manual tag overrides can be supplied for a single updater run with
`--tag-override LINE=TAG`, where `LINE` is the original WUD file line number.
Overrides require `--allow-tag-updates` and do not rewrite the todo file. Before
rewriting Compose files, the updater validates each final tag with
`docker manifest inspect`.

Compose tag rewrites only update direct `services.<name>.image` scalar values.
Interpolated image values such as `repo/app:${TAG}`, inherited image values, and
ambiguous Compose source layouts fail closed and leave the WUD entry pending for
manual review.

Older lines with a trailing `sha256=...` token are preserved as raw file lines
when cleanup rewrites the todo file. The display wrappers hide that suffix when
showing pending entries.

## Appends And Locking

`append-updates.sh` writes only when WUD sets `update_available=true`. It uses a
directory lock at `${WUD_OUT_FILE}.lock` and waits up to `WUD_LOCK_TIMEOUT`
seconds, defaulting to `30`.

When creating the todo file for the first time, the script uses mode `0660`. If
the file already exists, rewrites preserve its owner and mode unless `OUT_UID`
and `OUT_GID` are set.

For tag updates, WUD values such as `update_kind_remote_value` or `result_tag`
are converted into `tag=<new-tag>` when the tag value is safe.

## Applying Updates

Review pending entries without mutation:

```bash
updates --dry-run
docker-update-from-wud --dry-run
```

Apply all pending entries:

```bash
updates --yes
```

Apply tag updates explicitly:

```bash
updates --yes --allow-tag-updates
```

By default, matched Compose services are recreated without their dependencies.
If updating a service should recreate the whole Compose project, label that
service with `WUD-UPDATER-RECREATE-STACK=true`. When a matched running service
container has that label, the updater uses stack-level pull/recreate behavior
instead of service-scoped stop/up: it stops the project services and runs
`docker compose up -d --remove-orphans` without tearing down Compose networks.

Interactive `updates` runs show selected tag update entries and ask whether to
apply them as shown, skip them, or change the tag before handing off to
`docker-update-from-wud`.

Override a WUD-proposed tag directly:

```bash
docker-update-from-wud --yes --allow-tag-updates --tag-override 1=5.2.0
```

Interactive `updates` runs can apply all entries, select numbered entries,
exclude numbered entries, or skip. Unselected entries stay pending unless you
choose to remove them before running the selected updates.
