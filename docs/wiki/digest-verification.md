# Digest Verification

WUD can report digest-pinned updates in the shared todo file:

```text
repo/app:latest@sha256:abc123
repo/app@sha256:abc123
```

When the Python updater applies a digest-pinned line, it pulls the matched
Compose image first and then checks whether the local image can be tied back to
the digest WUD requested. Successful verification lets the updater recreate the
matched service or stack and remove the todo entry. A proven mismatch leaves the
entry pending and skips the recreate.

## Verification Sources

The fastest check uses Docker's local image metadata. If any local
`RepoDigests` value ends with the requested digest, the updater treats the image
as verified.

If `RepoDigests` does not contain the requested digest, the updater resolves the
current registry manifest for the image tag. It supports GHCR, Docker Hub
references such as `alpine:3.20`, and explicit registries such as
`quay.io/org/image:tag`.

For multi-platform images, Docker often records only the tag or index digest in
`RepoDigests`, not the platform-child manifest digest. In that case, the updater
fetches the child manifest from the registry and compares its config digest to
the local Docker image ID. If those match, the requested platform digest is
verified.

## Failure Policy

GHCR digest verification is treated as trusted and fail-closed. If the updater
can prove the requested GHCR digest is stale, unavailable, or points to a
different platform image, the update fails and the todo entry remains pending.

Non-GHCR digest verification is also fail-closed when the registry proves a
stale or mismatched digest. If a non-GHCR registry lookup cannot be completed
after `RepoDigests` does not match, the result is logged as untrusted and the
update continues. This avoids blocking Docker Hub, Quay, or private-registry
updates solely because the registry API or credentials were unavailable to the
helper.

## Logs

Hard failures are logged as `ERROR` entries with reason
`expected-digest-not-reached`. The log includes the local image ID, any seen
`RepoDigests`, the current tag digest when known, the matched child digest when
known, and registry or Docker manifest errors.

Untrusted non-GHCR results are logged as `WARN` entries with the same diagnostic
fields. They do not mark the run failed by themselves.

## Live Probe

The repository includes a Docker-gated live probe for checking registry behavior
against small public images:

```bash
tests/live-digest-verification.py alpine:3.20 quay.io/prometheus/busybox:latest
```

The probe pulls each image, reads Docker's local image ID and `RepoDigests`,
fetches registry manifests, and reports whether the tag digest and platform
child digest can be verified.
