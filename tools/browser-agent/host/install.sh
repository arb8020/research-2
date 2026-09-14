#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_PY="$SCRIPT_DIR/host.py"
MANIFEST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
MANIFEST="$MANIFEST_DIR/com.research.browser_agent.json"

chmod +x "$HOST_PY"

mkdir -p "$MANIFEST_DIR"

sed "s|HOST_PATH_PLACEHOLDER|$HOST_PY|" "$SCRIPT_DIR/com.research.browser_agent.json.template" > "$MANIFEST"

echo "Installed native messaging host manifest at:"
echo "  $MANIFEST"
echo ""
echo "Next steps:"
echo "  1. Load the extension in chrome://extensions (Developer mode -> Load unpacked)"
echo "  2. Copy the extension ID"
echo "  3. Edit: $MANIFEST"
echo "     Replace EXTENSION_ID_PLACEHOLDER with your extension ID"
echo "  4. Reload the extension"
