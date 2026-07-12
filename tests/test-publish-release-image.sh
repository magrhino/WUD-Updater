#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_TMP="$(mktemp -d "${TMPDIR:-/tmp}/wud-release-image-test.XXXXXX")"
trap 'rm -rf "$TEST_TMP"' EXIT
REAL_BASH="$(command -v bash)"

cat > "$TEST_TMP/bash" <<'FAKE_BASH'
#!/bin/bash
if [[ "${1:-}" == "tests/smoke-container-image.sh" ]]; then
  exit 0
fi
exec "$REAL_BASH" "$@"
FAKE_BASH
chmod +x "$TEST_TMP/bash"

cat > "$TEST_TMP/docker" <<'FAKE_DOCKER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"

if [[ "${FAIL_ARM64_VERIFY:-0}" == "1" && "$*" == "run --rm --platform linux/arm64 "* ]]; then
  exit 42
elif [[ "$*" == "buildx imagetools inspect --raw "* ]]; then
  printf '{"manifests":[{"digest":"sha256:%064d","platform":{"os":"linux","architecture":"amd64"}},{"digest":"sha256:%064d","platform":{"os":"linux","architecture":"arm64"}}]}\n' 1 2
elif [[ "$*" == "buildx imagetools inspect "* ]]; then
  printf 'Name: test\nDigest: sha256:%064d\n' 3
elif [[ "$*" == "image inspect --format "* ]]; then
  printf '{"org.opencontainers.image.version":"%s","org.opencontainers.image.revision":"%s"}\n' "$RELEASE_TAG" "$RELEASE_SHA"
elif [[ "$*" == *"trivy version --format json"* ]]; then
  printf '{"Version":"0.71.2"}\n'
fi
FAKE_DOCKER
chmod +x "$TEST_TMP/docker"

export PATH="$TEST_TMP:$PATH"
export REAL_BASH
export FAKE_DOCKER_LOG="$TEST_TMP/docker.log"
export REGISTRY="ghcr.io"
export IMAGE_NAME="magrhino/wudup"
export RELEASE_TAG="v1.2.3"
export VERSION="1.2.3"
export MINOR_VERSION="1.2"
export RELEASE_SHA="0123456789abcdef0123456789abcdef01234567"
export APT_REFRESH="workflow-123-attempt-1"
export GITHUB_REPOSITORY="magrhino/wudup"
export BUILDX_CACHE_FROM="type=gha,scope=test"
export BUILDX_CACHE_TO="type=gha,scope=test,mode=max"

cd "$REPO_ROOT"
bash .github/scripts/publish-release-image.sh trivy

grep -Fq -- "--build-arg APT_REFRESH=workflow-123-attempt-1" "$FAKE_DOCKER_LOG"
staging_ref="ghcr.io/magrhino/wudup:staging-${RELEASE_SHA}-trivy"
grep -Fq -- "pull --platform linux/amd64 ${staging_ref}@sha256:" "$FAKE_DOCKER_LOG"
grep -Fq -- "pull --platform linux/arm64 ${staging_ref}@sha256:" "$FAKE_DOCKER_LOG"
grep -Fq -- "buildx imagetools inspect --raw ${staging_ref}@sha256:" "$FAKE_DOCKER_LOG"
grep -Fq -- "run --rm --platform linux/amd64" "$FAKE_DOCKER_LOG"
grep -Fq -- "run --rm --platform linux/arm64" "$FAKE_DOCKER_LOG"
grep -Fq -- "buildx imagetools create --tag ghcr.io/magrhino/wudup:v1.2.3-trivy ${staging_ref}@sha256:" "$FAKE_DOCKER_LOG"

push_line="$(grep -n -m1 -- '--push' "$FAKE_DOCKER_LOG" | cut -d: -f1)"
verify_line="$(grep -n -m1 -- 'pull --platform linux/amd64' "$FAKE_DOCKER_LOG" | cut -d: -f1)"
promote_line="$(grep -n -m1 -- 'imagetools create --tag' "$FAKE_DOCKER_LOG" | cut -d: -f1)"
if (( push_line >= verify_line || verify_line >= promote_line )); then
  printf 'release image was not staged, verified, then promoted\n' >&2
  exit 1
fi

: > "$FAKE_DOCKER_LOG"
export FAIL_ARM64_VERIFY=1
if bash .github/scripts/publish-release-image.sh trivy; then
  printf 'release image verification failure unexpectedly succeeded\n' >&2
  exit 1
fi
if grep -Fq -- 'imagetools create --tag' "$FAKE_DOCKER_LOG"; then
  printf 'failed release image was promoted to production tags\n' >&2
  exit 1
fi
unset FAIL_ARM64_VERIFY

: > "$FAKE_DOCKER_LOG"
export APT_REFRESH="workflow-123-attempt-2"
bash .github/scripts/publish-release-image.sh trivy
grep -Fq -- "--build-arg APT_REFRESH=workflow-123-attempt-2" "$FAKE_DOCKER_LOG"
if grep -Fq -- "--build-arg APT_REFRESH=workflow-123-attempt-1" "$FAKE_DOCKER_LOG"; then
  printf 'release retry reused the previous apt freshness token\n' >&2
  exit 1
fi

printf 'ok - release image freshness and platform verification\n'
