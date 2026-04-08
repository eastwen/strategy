#!/bin/bash
# Kill any existing processes
pkill -9 -f chrome 2>/dev/null || true
pkill -9 -f agent-browser 2>/dev/null || true
sleep 2

# Start with --no-sandbox
exec /home/admin/.local/share/pnpm/global/5/.pnpm/agent-browser@0.20.14/node_modules/agent-browser/bin/agent-browser-linux-x64 "$@" --args "--no-sandbox"
