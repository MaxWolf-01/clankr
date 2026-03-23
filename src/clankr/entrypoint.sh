#!/bin/bash
set -euo pipefail

if [ -x "$CLAUDE_CONFIG_DIR/init" ]; then
    "$CLAUDE_CONFIG_DIR/init" >&2
fi

exec claude --dangerously-skip-permissions "$@"
