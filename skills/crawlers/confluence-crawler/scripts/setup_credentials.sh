#!/usr/bin/env bash
# One-time credential capture for confluence-crawler.
# Writes to ~/.config/confluence-crawler/config.env with mode 0600.
# The API token is never echoed, logged, or passed on the command line.
#
# Supports both Atlassian Cloud and Confluence Server/Data Center.
# Cloud is auto-detected when the host ends with .atlassian.net.

set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/confluence-crawler"
CONFIG_FILE="$CONFIG_DIR/config.env"

umask 077
mkdir -p "$CONFIG_DIR"

printf 'Confluence base URL: '
printf '\n  - Cloud example:  https://your-site.atlassian.net\n'
printf '  - Server example: https://confluence.corp.example.com\n'
printf '> '
read -r BASE_URL
BASE_URL="${BASE_URL%/}"
if [[ -z "$BASE_URL" ]]; then
  echo "error: base URL is required" >&2
  exit 1
fi
if [[ ! "$BASE_URL" =~ ^https?:// ]]; then
  echo "error: base URL must start with http:// or https://" >&2
  exit 1
fi

HOST="$(printf '%s' "$BASE_URL" | sed -E 's#^https?://([^/]+).*#\1#' | tr '[:upper:]' '[:lower:]')"
FLAVOR="server"
if [[ "$HOST" == *.atlassian.net ]]; then
  FLAVOR="cloud"
  # Cloud's Confluence REST API is served under /wiki.
  if [[ "$BASE_URL" != */wiki && "$BASE_URL" != */wiki/* ]]; then
    BASE_URL="$BASE_URL/wiki"
    echo "detected Atlassian Cloud — appended /wiki → $BASE_URL"
  else
    echo "detected Atlassian Cloud"
  fi
else
  echo "detected Confluence Server / Data Center"
fi

EMAIL=""
if [[ "$FLAVOR" == "cloud" ]]; then
  printf 'Atlassian account email: '
  read -r EMAIL
  if [[ -z "$EMAIL" ]]; then
    echo "error: email is required for Cloud" >&2
    exit 1
  fi
fi

if [[ "$FLAVOR" == "cloud" ]]; then
  printf 'API token from https://id.atlassian.com/manage-profile/security/api-tokens (hidden): '
else
  printf 'Personal Access Token (hidden): '
fi
stty -echo
trap 'stty echo' EXIT INT TERM
read -r API_TOKEN
stty echo
trap - EXIT INT TERM
printf '\n'

if [[ -z "$API_TOKEN" ]]; then
  echo "error: API token is required" >&2
  exit 1
fi

TMP="$(mktemp "$CONFIG_DIR/.config.XXXXXX")"
chmod 600 "$TMP"
{
  printf 'CONFLUENCE_BASE_URL=%q\n' "$BASE_URL"
  printf 'CONFLUENCE_FLAVOR=%q\n' "$FLAVOR"
  if [[ -n "$EMAIL" ]]; then
    printf 'CONFLUENCE_EMAIL=%q\n' "$EMAIL"
  fi
  printf 'CONFLUENCE_API_TOKEN=%q\n' "$API_TOKEN"
} > "$TMP"
mv "$TMP" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

unset API_TOKEN

echo "Wrote credentials to $CONFIG_FILE (mode 0600)."
echo "Verify connectivity with: python scripts/crawl_space.py --check"
