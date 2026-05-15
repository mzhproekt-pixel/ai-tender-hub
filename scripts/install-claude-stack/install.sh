#!/usr/bin/env bash
# Мерджит settings.snippet.json в ~/.claude/settings.json для установки
# 4 плагинов Claude Code (superpowers / code-review / claude-mem / context-mode).
set -euo pipefail

CLAUDE_HOME="${HOME}/.claude"
SETTINGS="${CLAUDE_HOME}/settings.json"
SNIPPET="$(dirname "$(readlink -f "$0")")/settings.snippet.json"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: требуется jq (apt install jq / brew install jq)" >&2
  exit 1
fi

mkdir -p "$CLAUDE_HOME"

if [[ -f "$SETTINGS" ]]; then
  ts="$(date +%Y%m%d-%H%M%S)"
  cp "$SETTINGS" "${SETTINGS}.bak.${ts}"
  echo "backup: ${SETTINGS}.bak.${ts}"
else
  echo '{}' > "$SETTINGS"
fi

tmp="$(mktemp)"
jq -s '.[0] * .[1]' "$SETTINGS" "$SNIPPET" > "$tmp"
mv "$tmp" "$SETTINGS"
echo "updated: $SETTINGS"

cat <<'EOF'

next steps in Claude Code:
  /plugin list      # должны быть 4 плагина enabled
  /skills           # кастомные + плагинные скиллы

если плагины не появились — перезапустите Claude Code.
EOF
