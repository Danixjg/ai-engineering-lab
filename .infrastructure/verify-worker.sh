#!/usr/bin/env bash
# Verify this host against .infrastructure/worker-spec.yaml.  The script only
# reads CLI status; it does not log in, start services, or expose credentials.
set -uo pipefail

export PATH="$HOME/.opencode/bin:${NPM_CONFIG_PREFIX:-$HOME/.npm-global}/bin:$HOME/.local/bin:$PATH"
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC_FILE="$ROOT_DIR/.infrastructure/worker-spec.yaml"
failures=0

if [[ ! -f "$SPEC_FILE" ]]; then
  echo "Missing worker specification: $SPEC_FILE" >&2
  exit 2
fi

spec_value() {
  local section="$1" key="$2"
  awk -v section="$section" -v key="$key" '
    $0 ~ "^" section ":" { inside=1; next }
    inside && /^[^[:space:]]/ { exit }
    inside && $0 ~ "^[[:space:]]+" key ":" {
      value=$0
      sub("^[[:space:]]+" key ":[[:space:]]*", "", value)
      gsub(/["[:space:]]/, "", value)
      print value
      exit
    }
  ' "$SPEC_FILE"
}

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

report() {
  local label="$1" result="$2" detail="${3:-}"
  printf '%-14s %-4s%s\n' "$label" "$result" "${detail:+  ($detail)}"
  [[ "$result" == "PASS" ]] || failures=$((failures + 1))
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

version_at_least() {
  local command="$1" required="$2" raw token actual="" index
  local -a actual_parts required_parts
  raw="$($command --version 2>&1)" || return 1
  for token in $(printf '%s\n' "$raw" | sed -E 's/[^0-9.]+/ /g'); do
    [[ "$token" =~ ^[0-9]+(\.[0-9]+){0,2}$ ]] && actual="$token"
  done
  [[ -n "$actual" ]] || return 1
  IFS=. read -r -a actual_parts <<< "$actual"
  IFS=. read -r -a required_parts <<< "$required"
  for index in 0 1 2; do
    if (( ${actual_parts[index]:-0} > ${required_parts[index]:-0} )); then return 0; fi
    if (( ${actual_parts[index]:-0} < ${required_parts[index]:-0} )); then return 1; fi
  done
  return 0
}

# A few CLIs print authentication failures while returning success, so inspect
# their text as well as their status code.  This deliberately avoids printing
# the command output, which can contain account identifiers.
is_authenticated() {
  local output
  output="$($@ 2>&1)" || return 1
  ! printf '%s' "$output" | grep -Eqi \
    'not[ -]?logged|not authenticated|unauthenticated|invalid|expired|log in|login required|sign in'
}

if has_command multica; then
  report "Multica" PASS "$(multica --version 2>&1 | head -n 1)"
  if multica daemon status --output json 2>/dev/null | grep -Eq '"status"[[:space:]]*:[[:space:]]*"(running|ready)"'; then
    report "Daemon" PASS
  else
    report "Daemon" FAIL "start with: multica daemon start"
  fi
else
  report "Multica" FAIL "command not found"
  report "Daemon" FAIL "Multica unavailable"
fi

kiro_command="$(agent_value kiro command)"
kiro_version="$(agent_value kiro version)"
kiro_required="$(agent_value kiro required)"
if has_command "$kiro_command" && version_at_least "$kiro_command" "$kiro_version"; then
  report "Kiro" PASS "$($kiro_command --version 2>&1 | head -n 1)"
  if is_authenticated "$kiro_command" whoami; then
    report "Kiro auth" PASS
  elif [[ "$kiro_required" == "true" ]]; then
    report "Kiro auth" FAIL "run: $kiro_command login"
  else
    printf '%-14s %-4s%s\n' "Kiro auth" "SKIP" "  (optional runtime not authenticated)"
  fi
elif [[ "$kiro_required" == "true" ]]; then
  report "Kiro" FAIL "requires $kiro_command $kiro_version.x"
  report "Kiro auth" FAIL "Kiro unavailable"
else
  printf '%-14s %-4s%s\n' "Kiro" "SKIP" "  (optional runtime unavailable)"
fi

codex_command="$(agent_value codex command)"
codex_version="$(agent_value codex version)"
if has_command "$codex_command" && version_at_least "$codex_command" "$codex_version"; then
  report "Codex" PASS "$($codex_command --version 2>&1 | tail -n 1)"
  if is_authenticated "$codex_command" login status; then
    report "Codex auth" PASS
  else
    report "Codex auth" FAIL "run: $codex_command login"
  fi
else
  report "Codex" FAIL "requires $codex_command $codex_version.x"
  report "Codex auth" FAIL "Codex unavailable"
fi

opencode_command="$(agent_value opencode command)"
opencode_version="$(agent_value opencode version)"
if has_command "$opencode_command" && version_at_least "$opencode_command" "$opencode_version"; then
  report "OpenCode" PASS "$($opencode_command --version 2>&1 | tail -n 1)"
else
  report "OpenCode" FAIL "requires $opencode_command $opencode_version+"
fi

if has_command ollama && ollama list >/dev/null 2>&1; then
  report "Ollama" PASS
else
  report "Ollama" FAIL "start the local model server, then run: ollama list"
fi

if has_command git; then report "Git" PASS "$(git --version)"; else report "Git" FAIL "command not found"; fi

if has_command docker && docker info >/dev/null 2>&1; then
  report "Docker" PASS
else
  report "Docker" FAIL "CLI missing or daemon unavailable"
fi

python_required="$(spec_value languages python)"
if has_command python3 && version_at_least python3 "$python_required"; then
  report "Python" PASS "$(python3 --version 2>&1)"
else
  report "Python" FAIL "requires $python_required.x"
fi

node_required="$(spec_value languages node)"
if has_command node && version_at_least node "$node_required"; then
  report "Node" PASS "$(node --version 2>&1)"
else
  report "Node" FAIL "requires $node_required.x"
fi

if (( failures == 0 )); then
  printf '\nWORKER READY\n'
  exit 0
fi

printf '\nWORKER NOT READY (%d check(s) failed)\n' "$failures"
exit 1
