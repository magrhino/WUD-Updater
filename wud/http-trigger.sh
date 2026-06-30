#!/bin/sh
# POST WUD command-trigger events to WUDup's API trigger endpoint.

TRIGGER_URL="${WUDUP_TRIGGER_URL:-http://wudup:7417/api/v1/wud/triggers/update}"
TOKEN="${WUDUP_TRIGGER_TOKEN:-}"

if [ -z "$TOKEN" ] && [ -n "${WUDUP_TRIGGER_TOKEN_FILE:-}" ]; then
  TOKEN="$(cat "$WUDUP_TRIGGER_TOKEN_FILE" 2>/dev/null || true)"
fi

if [ -z "$TOKEN" ]; then
  echo "WUDUP_TRIGGER_TOKEN or WUDUP_TRIGGER_TOKEN_FILE is required" >&2
  exit 1
fi

case "${update_available:-}" in
  false|0|no|off)
    UPDATE_AVAILABLE=false
    ;;
  *)
    UPDATE_AVAILABLE=true
    ;;
esac

PAYLOAD=$(jq -nc \
  --argjson updateAvailable "$UPDATE_AVAILABLE" \
  --arg id "${id:-}" \
  --arg container_id "${container_id:-}" \
  --arg name "${name:-}" \
  --arg image_name "${image_name:-}" \
  --arg image_tag "${image_tag_value:-}" \
  '{updateAvailable:$updateAvailable,id:$id,container_id:$container_id,name:$name,image_name:$image_name,image:{name:$image_name,tag:$image_tag}}')

curl --fail --silent --show-error \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$TRIGGER_URL" >/dev/null
