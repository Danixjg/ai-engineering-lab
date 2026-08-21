#!/usr/bin/env bash
# Bootstrap the non-secret dependencies for a Linux worker.
# It intentionally leaves Kiro installation and all authentication interactive.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SPEC_FILE="$ROOT_DIR/.infrastructure/worker-spec.yaml"

agent_value() {
  local agent="$1" key="$2"
  awk -v agent="$agent" -v key="$key" '
    /^agents:/ { in_agents=1; next }
    in_agents && /^[^[:space:]]/ { exit }
    in_agents && $0 ~ "^  " agent ":" { in_agent=1; next }
    in_agent && /^  [^[:space:]]/ { exit }
    in_agent && $0 ~ "^    " key ":" {
      value=$0
      sub("^    " key ":[[:space:]]*", "", value)
      gsub(/["[:space:]]/, "", value)
      print value
      exit
    }
  ' "$SPEC_FILE"
}

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This bootstrap currently supports apt-based Linux hosts." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install --yes git docker.io curl

if ! command -v mise >/dev/null 2>&1; then
  curl https://mise.run | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
eval "$(mise activate bash)"
python_version="$(awk '/^languages:/{in_languages=1; next} in_languages && /^[^[:space:]]/{exit} in_languages && /^[[:space:]]+python:/{gsub(/["[:space:]]/, "", $2); print $2}' "$SPEC_FILE")"
node_version="$(awk '/^languages:/{in_languages=1; next} in_languages && /^[^[:space:]]/{exit} in_languages && /^[[:space:]]+node:/{gsub(/["[:space:]]/, "", $2); print $2}' "$SPEC_FILE")"
mise use --global "python@$python_version" "node@$node_version"

npm install --global "@openai/codex@$(agent_value codex version)"

export PATH="$HOME/.local/bin:$PATH"
if ! command -v kiro-cli >/dev/null 2>&1; then
  curl -fsSL https://cli.kiro.dev/install | bash
fi

echo "Docker may require a group/session refresh after installation."
echo "Authenticate required CLIs, start Multica's daemon, then run:"
echo "  $ROOT_DIR/.infrastructure/verify-worker.sh"
