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
as successful. See [Digest Verification](digest-verification.md) for registry
trust behavior and live verification notes.

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

When `WUD_DIGEST_PIN_UPDATES=true`, approved tag updates are planned as
digest-pin rewrites. During dry-run planning, the updater resolves the proposed
tag to a target digest and records planned actions (the planned resolved tag and
planned `wud.tag.include` regex) without mutating Compose or performing pulls.
During the apply/execution phase, the updater temporarily rewrites Compose to
the resolved tag for `docker compose pull`, verifies the pulled local image
against the planned digest, then writes the final image as
`repo/app@sha256:<digest>`. The Compose edit adds
`# wud-updater.resolved-tag=<tag>` above `image:` and sets `wud.tag.include` to
an exact regex for the resolved tag. Dry-run remains non-mutating; Compose edits
and final digest writes happen only during apply. Lines without a safe resolved
tag, custom compound `wud.tag.include` regexes, YAML anchors/aliases,
interpolation, and inherited image values fail closed.

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

Apply approved tag updates as digest-pinned Compose references:

```bash
WUD_DIGEST_PIN_UPDATES=true updates --yes --allow-tag-updates
```

By default, matched Compose services are recreated without their dependencies.
If updating a service should recreate the whole Compose project, label that
service with `WUD-UPDATER-RECREATE-STACK=true`. When a matched running service
container has that label, the updater uses stack-level pull/recreate behavior
instead of service-scoped stop/up: it stops the project services and runs
`docker compose up -d --remove-orphans` without tearing down Compose networks.

Interactive `updates` runs show selected tag update entries and ask whether to
apply them as shown, skip them, change the tag, or exclude the proposed exact
tag before handing off to `docker-update-from-wud`.

When you choose to exclude a tag, the updater writes WUD's native
`wud.tag.exclude` label into the matched Compose service definition. If every
service using the same image repository can be updated cleanly, the exclusion is
applied repo-wide; otherwise it falls back to the selected service. Existing
user-authored exclude regexes are preserved and the updater stores managed exact
tag exclusions in SQLite. You can also let the wrapper recreate affected
services immediately so WUD sees the new container labels before its next scan.

Override a WUD-proposed tag directly:

```bash
docker-update-from-wud --yes --allow-tag-updates --tag-override 1=5.2.0
```

Exclude a WUD-proposed tag directly:

```bash
docker-update-from-wud --yes --exclude-tag-lines 1 --recreate-excluded-services
```

Interactive `updates` runs can apply all entries, select numbered entries,
exclude numbered entries, or skip. Unselected entries stay pending unless you
choose to remove them before running the selected updates.
