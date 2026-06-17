#!/usr/bin/env bash
# shellcheck disable=SC2034

# Shared curl policy for WUD release-note helpers. This file is sourced by Bash
# scripts and intentionally does not enable or change shell options.

_wud_http_curl_args=(
  --fail
  --silent
  --show-error
  --location
  --retry 3
  --retry-delay 1
  --connect-timeout 5
  --max-time 20
)

HTTP_DISCORD_ERROR=""

http_get_to_file() {
  local output_file="$1" url="$2"
  shift 2

  curl "${_wud_http_curl_args[@]}" "$@" -o "$output_file" "$url"
  return $?
}

http_effective_url() {
  local url="$1"
  shift

  curl "${_wud_http_curl_args[@]}" "$@" -o /dev/null -w '%{url_effective}' "$url"
  return $?
}

http_post_discord_json() {
  local webhook_url="$1" payload="$2" response rc code

  HTTP_DISCORD_ERROR=""

  if response="$(curl "${_wud_http_curl_args[@]}" \
    -H "Content-Type: application/json" \
    -d "$payload" \
    -w '\n%{http_code}' \
    "$webhook_url")"; then
    rc=0
  else
    rc=$?
  fi
  code="${response##*$'\n'}"

  if [[ "$code" =~ ^[0-9][0-9][0-9]$ ]]; then
    if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
      return 0
    fi
    HTTP_DISCORD_ERROR="Discord webhook error $code"
    return 1
  fi

  if (( rc != 0 )); then
    HTTP_DISCORD_ERROR="Discord webhook request failed to send"
    return "$rc"
  fi

  HTTP_DISCORD_ERROR="Discord webhook response missing HTTP status"
  return 1
}
