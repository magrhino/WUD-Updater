#!/usr/bin/env bash
set -euo pipefail

variant="${1:-}"
case "$variant" in
  default)
    suffix=""
    ;;
  trivy)
    suffix="-trivy"
    ;;
  *)
    printf 'Usage: %s default|trivy\n' "$0" >&2
    exit 2
    ;;
esac

image="$REGISTRY/$IMAGE_NAME"
expected_platforms="linux/amd64 linux/arm64"
production_tags=(
  "$image:$RELEASE_TAG$suffix"
  "$image:$VERSION$suffix"
  "$image:$MINOR_VERSION$suffix"
  "$image:latest$suffix"
)
staging_ref="$image:staging-${RELEASE_SHA}${suffix}"
label_args=(
  --label "org.opencontainers.image.source=https://github.com/$GITHUB_REPOSITORY"
  --label "org.opencontainers.image.revision=$RELEASE_SHA"
  --label "org.opencontainers.image.version=$RELEASE_TAG"
)
build_args=(--build-arg "APT_REFRESH=$APT_REFRESH")
tag_args=(-t "$staging_ref")

build_image() {
  local platform="$1"
  local output_arg="$2"
  local docker_args=(buildx build --platform "$platform")
  shift 2
  if [[ "$variant" == "trivy" ]]; then
    docker_args+=(--target wudup-trivy)
  fi

  docker "${docker_args[@]}" \
    "$@" \
    "${label_args[@]}" \
    "${build_args[@]}" \
    "${tag_args[@]}" \
    --cache-from "$BUILDX_CACHE_FROM" \
    --cache-to "$BUILDX_CACHE_TO" \
    "$output_arg" \
    .
}

build_image linux/amd64 --load
bash tests/smoke-container-image.sh "$staging_ref"
if [[ "$variant" == "trivy" ]]; then
  docker run --rm "$staging_ref" trivy --version
fi

build_image linux/amd64,linux/arm64 --push --provenance=false
staging_digest="$(
  docker buildx imagetools inspect "$staging_ref" |
    sed -n 's/^Digest:[[:space:]]*//p'
)"
if [[ ! "$staging_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'Could not resolve staged manifest digest for %s\n' "$staging_ref" >&2
  exit 1
fi
verified_ref="${staging_ref}@${staging_digest}"
release_manifest="$(docker buildx imagetools inspect --raw "$verified_ref")"
expected_trivy_version="$(sed -n 's/^FROM aquasec\/trivy:\([^@ ]*\).*/\1/p' Dockerfile)"
for platform in $expected_platforms; do
  os="${platform%/*}"
  architecture="${platform#*/}"
  digest="$(
    jq -r \
      --arg os "$os" \
      --arg architecture "$architecture" \
      '.manifests[] | select(.platform.os == $os and .platform.architecture == $architecture) | .digest' \
      <<<"$release_manifest"
  )"
  if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'Could not resolve %s platform digest for %s\n' "$platform" "$staging_ref" >&2
    exit 1
  fi

  immutable_ref="${staging_ref}@${digest}"
  docker pull --platform "$platform" "$immutable_ref"
  labels="$(docker image inspect --format '{{json .Config.Labels}}' "$immutable_ref")"
  jq -e \
    --arg version "$RELEASE_TAG" \
    --arg revision "$RELEASE_SHA" \
    '."org.opencontainers.image.version" == $version and ."org.opencontainers.image.revision" == $revision' \
    <<<"$labels" >/dev/null

  docker run --rm --platform "$platform" "$immutable_ref" sh -ec '
    packages="libgnutls30 libssl3 openssl libgcrypt20"
    dpkg-query -W $packages
    apt-get -o Acquire::Retries=3 update >/dev/null
    upgrades="$(apt-get -s upgrade)"
    for package in $packages; do
      if printf "%s\n" "$upgrades" | grep -Eq "^Inst ${package}(:[^ ]+)? "; then
        printf "Published image has an available upgrade for %s\n" "$package" >&2
        exit 1
      fi
    done
  '

  if [[ "$variant" == "trivy" ]]; then
    actual_trivy_version="$(
      docker run --rm --platform "$platform" "$immutable_ref" \
        trivy version --format json | jq -r '.Version'
    )"
    if [[ "$actual_trivy_version" != "$expected_trivy_version" ]]; then
      printf 'Expected Trivy %s for %s, got %s\n' \
        "$expected_trivy_version" "$platform" "$actual_trivy_version" >&2
      exit 1
    fi
  fi
done

for ref in "${production_tags[@]}"; do
  docker buildx imagetools create --tag "$ref" "$verified_ref"
  platforms="$(
    docker buildx imagetools inspect --raw "$ref" |
      jq -r '[.manifests[].platform | "\(.os)/\(.architecture)"] | sort | unique | join(" ")'
  )"
  if [[ "$platforms" != "$expected_platforms" ]]; then
    printf 'Expected %s to publish platforms "%s", got "%s"\n' "$ref" "$expected_platforms" "$platforms" >&2
    exit 1
  fi
done
