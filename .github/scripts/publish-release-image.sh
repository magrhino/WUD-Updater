#!/usr/bin/env bash
set -euo pipefail

variant="${1:-}"
case "$variant" in
  default)
    suffix=""
    target_args=()
    ;;
  trivy)
    suffix="-trivy"
    target_args=(--target wudup-trivy)
    ;;
  *)
    printf 'Usage: %s default|trivy\n' "$0" >&2
    exit 2
    ;;
esac

image="$REGISTRY/$IMAGE_NAME"
expected_platforms="linux/amd64 linux/arm64"
tags=(
  "$image:$RELEASE_TAG$suffix"
  "$image:$VERSION$suffix"
  "$image:$MINOR_VERSION$suffix"
  "$image:latest$suffix"
)
label_args=(
  --label "org.opencontainers.image.source=https://github.com/$GITHUB_REPOSITORY"
  --label "org.opencontainers.image.revision=$RELEASE_SHA"
  --label "org.opencontainers.image.version=$RELEASE_TAG"
)
tag_args=()
for tag in "${tags[@]}"; do
  tag_args+=(-t "$tag")
done

build_image() {
  local platform="$1"
  local output_arg="$2"
  shift 2

  docker buildx build \
    --platform "$platform" \
    "${target_args[@]}" \
    "$@" \
    "${label_args[@]}" \
    "${tag_args[@]}" \
    --cache-from "$BUILDX_CACHE_FROM" \
    --cache-to "$BUILDX_CACHE_TO" \
    "$output_arg" \
    .
}

build_image linux/amd64 --load
bash tests/smoke-container-image.sh "${tags[0]}"
if [[ "$variant" == "trivy" ]]; then
  docker run --rm "${tags[0]}" trivy --version
fi

build_image linux/amd64,linux/arm64 --push --provenance=false
for ref in "${tags[@]}"; do
  platforms="$(
    docker buildx imagetools inspect --raw "$ref" |
      jq -r '[.manifests[].platform | "\(.os)/\(.architecture)"] | sort | unique | join(" ")'
  )"

  if [[ "$platforms" != "$expected_platforms" ]]; then
    printf 'Expected %s to publish platforms "%s", got "%s"\n' "$ref" "$expected_platforms" "$platforms" >&2
    exit 1
  fi
done
