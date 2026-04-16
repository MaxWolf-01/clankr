#!/bin/bash
set -euo pipefail

if [ -x "$CLAUDE_CONFIG_DIR/init" ]; then
    source "$CLAUDE_CONFIG_DIR/init" >&2
fi

exec claude --dangerously-skip-permissions "$@"
