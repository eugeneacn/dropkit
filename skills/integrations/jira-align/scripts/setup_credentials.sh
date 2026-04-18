#!/usr/bin/env bash
# One-time credential capture for jira-align.
# Writes to ~/.config/dropkit/credentials.env with mode 0600.
# The API token is never echoed, logged, or passed on the command line.
#
# The file is shared with other dropkit skills (e.g. confluence-crawler);
# this script merges Jira Align keys into the existing file without touching
# other products' keys.
#
# Works for both Atlassian Cloud (*.jiraalign.com / legacy *.agilecraft.com)
# and self-hosted / on-prem installs. Authentication is identical either way
# — a bearer token generated on the user's Jira Align Profile page.

set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dropkit"
CONFIG_FILE="$CONFIG_DIR/credentials.env"

umask 077
mkdir -p "$CONFIG_DIR"

printf 'Jira Align base URL:\n'
printf '  - Cloud example:   https://your-site.jiraalign.com\n'
printf '  - On-prem example: https://jiraalign.corp.example.com\n'
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
FLAVOR="onprem"
if [[ "$HOST" == *.jiraalign.com || "$HOST" == *.agilecraft.com ]]; then
  FLAVOR="cloud"
  echo "detected Atlassian Cloud ($HOST)"
else
  echo "detected self-hosted / on-prem ($HOST)"
fi

printf 'Personal API Token from Jira Align (avatar → Profile → API Token, hidden): '
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

# Rewrite the config file, preserving any non-JIRAALIGN_* keys so that
# other skills sharing this file (e.g. confluence-crawler) keep working.
TMP="$(mktemp "$CONFIG_DIR/.credentials.XXXXXX")"
chmod 600 "$TMP"
if [[ -f "$CONFIG_FILE" ]]; then
  grep -v -E '^(JIRAALIGN_BASE_URL|JIRAALIGN_API_TOKEN|JIRAALIGN_FLAVOR)=' "$CONFIG_FILE" > "$TMP" || true
fi
{
  printf 'JIRAALIGN_BASE_URL=%q\n' "$BASE_URL"
  printf 'JIRAALIGN_FLAVOR=%q\n' "$FLAVOR"
  printf 'JIRAALIGN_API_TOKEN=%q\n' "$API_TOKEN"
} >> "$TMP"
mv "$TMP" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

unset API_TOKEN

echo "Wrote credentials to $CONFIG_FILE (mode 0600)."
echo "Verify connectivity with: python scripts/jira_align.py check"
