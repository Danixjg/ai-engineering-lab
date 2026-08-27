#!/usr/bin/env bash
# Bootstrap the non-secret dependencies for a macOS worker.
# Model selection, authentication, and Docker Desktop's first-run approval remain
# interactive by design; this script never accepts or stores credentials.
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

command -v brew >/dev/null 2>&1 || {
  echo "Homebrew is required. Install it from https://brew.sh, then rerun this script." >&2
  exit 1
}

brew install git mise
if ! command -v docker >/dev/null 2>&1; then
  brew install --cask docker
  echo "Docker Desktop was installed. Open it once and accept its prompts before verification."
fi

eval "$(mise activate bash)"
python_version="$(awk '/^languages:/{in_languages=1; next} in_languages && /^[^[:space:]]/{exit} in_languages && /^[[:space:]]+python:/{gsub(/["[:space:]]/, "", $2); print $2}' "$SPEC_FILE")"
node_version="$(awk '/^languages:/{in_languages=1; next} in_languages && /^[^[:space:]]/{exit} in_languages && /^[[:space:]]+node:/{gsub(/["[:space:]]/, "", $2); print $2}' "$SPEC_FILE")"
mise use --global "python@$python_version" "node@$node_version"

npm install --global "@openai/codex@$(agent_value codex version)"
npm install --global "opencode-ai@$(agent_value opencode version)"

if ! command -v ollama >/dev/null 2>&1; then
  brew install ollama
fi

"$ROOT_DIR/bin/multiengin" install-path

echo "Bootstrap complete. Start Ollama, configure OpenCode, authenticate required CLIs, start Multica's daemon, then run:"
echo "  $ROOT_DIR/.infrastructure/verify-worker.sh"
