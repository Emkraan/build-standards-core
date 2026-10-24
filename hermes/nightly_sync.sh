#!/bin/bash
# Compatibility shim. The nightly job is hermes/nightly.py; consumers set up before it existed call
# this file as `nightly_sync.sh [core clone] [skills dir]` and are moved onto it here, so they pick up
# the Hermes setup and UI consumer steps without anyone touching their cron. New consumers run
# hermes/setup.py instead (see AGENTS.md at the repo root).
set -u
CORE="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
args=(--core "$CORE")
[ -n "${2:-}" ] && args+=(--skills-dest "$2")
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.cargo/bin:$PATH"
exec python3 "$CORE/hermes/nightly.py" "${args[@]}"
