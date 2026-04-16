#!/bin/bash
set -euo pipefail

if [ -x "$HOME/.pi/init" ]; then
    source "$HOME/.pi/init" >&2
fi

exec pi "$@"
