#!/bin/sh
# Container start-up: per-container secrets and data folders, then the given command.
set -e

mkdir -p "$HOME" "$OSINT_DATA_DIR/plugins_user"

# SearXNG needs a secret key; it is generated here so that no two containers share one
# (the image itself never contains it).
S=/app/tools/searxng
if [ -d "$S/src" ] && [ ! -f "$S/settings.yml" ]; then
  SECRET=$(/app/.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')
  sed "s/__SECRET__/$SECRET/" "$S/settings.example.yml" > "$S/settings.yml"
  chmod 600 "$S/settings.yml"
fi

# Convenience: `docker compose run --rm osint-panel osint search …`
if [ "$1" = "osint" ]; then
  shift
  exec /app/.venv/bin/python /app/panel/cli.py "$@"
fi

exec "$@"
