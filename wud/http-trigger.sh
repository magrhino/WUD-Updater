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

json_string() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

case "${update_available:-}" in
  false|0|no|off)
    UPDATE_AVAILABLE=false
    ;;
  *)
    UPDATE_AVAILABLE=true
    ;;
esac

PAYLOAD=$(printf \
  '{"updateAvailable":%s,"id":"%s","container_id":"%s","name":"%s","image_name":"%s","image":{"name":"%s","tag":"%s"}}' \
  "$UPDATE_AVAILABLE" \
  "$(json_string "${id:-}")" \
  "$(json_string "${container_id:-}")" \
  "$(json_string "${name:-}")" \
  "$(json_string "${image_name:-}")" \
  "$(json_string "${image_name:-}")" \
  "$(json_string "${image_tag_value:-}")")

curl --fail --silent --show-error \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$TRIGGER_URL" >/dev/null
