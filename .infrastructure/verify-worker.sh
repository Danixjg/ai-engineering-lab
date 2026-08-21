#!/usr/bin/env bash
# Verify this host against .infrastructure/worker-spec.yaml.  The script only
# reads CLI status; it does not log in, start services, or expose credentials.
set -uo pipefail

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

version_matches() {
  local command="$1" required="$2" raw major
  raw="$($command --version 2>&1)" || return 1
  major="${required%%.*}"
  [[ "$raw" =~ (^|[^0-9])${required//./\\.}([.[:space:]]|$) ]] || \
    [[ "$required" != *.* && "$raw" =~ (^|[^0-9])${major}([.[:space:]]|$) ]]
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
if has_command "$kiro_command" && version_matches "$kiro_command" "$kiro_version"; then
  report "Kiro" PASS "$($kiro_command --version 2>&1 | head -n 1)"
  if is_authenticated "$kiro_command" whoami; then
    report "Kiro auth" PASS
  else
    report "Kiro auth" FAIL "run: $kiro_command login"
  fi
else
  report "Kiro" FAIL "requires $kiro_command $kiro_version.x"
  report "Kiro auth" FAIL "Kiro unavailable"
fi

codex_command="$(agent_value codex command)"
codex_version="$(agent_value codex version)"
if has_command "$codex_command" && version_matches "$codex_command" "$codex_version"; then
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

if has_command git; then report "Git" PASS "$(git --version)"; else report "Git" FAIL "command not found"; fi

if has_command docker && docker info >/dev/null 2>&1; then
  report "Docker" PASS
else
  report "Docker" FAIL "CLI missing or daemon unavailable"
fi

python_required="$(spec_value languages python)"
if has_command python3 && version_matches python3 "$python_required"; then
  report "Python" PASS "$(python3 --version 2>&1)"
else
  report "Python" FAIL "requires $python_required.x"
fi

node_required="$(spec_value languages node)"
if has_command node && version_matches node "$node_required"; then
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
