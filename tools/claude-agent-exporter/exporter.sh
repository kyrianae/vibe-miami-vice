#!/bin/sh
# Writes a Prometheus textfile metric `claude_agent{agent="<type>"} 0|1`
# for each known Claude Code subagent type, based on how recently its
# transcript file was modified under ~/.claude/projects/*/subagents/ —
# a proxy for "currently working", not an exact "LLM call in flight"
# signal (there is no such API). A type counts as active (1) if at
# least one of its agent instances has a transcript modified within
# FRESH_SECONDS; otherwise 0. Runs forever, rewriting the file every
# INTERVAL seconds (atomic write: temp file + rename).
set -eu

PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-/claude-projects}"
OUT_FILE="${OUT_FILE:-/metrics/claude_agents.prom}"
FRESH_SECONDS="${FRESH_SECONDS:-20}"
INTERVAL="${INTERVAL:-15}"

# Classify from the human-readable `description` field written at
# dispatch time (e.g. "Pessimiste action 22 class validation"). Order
# matters: "testeur-global" must be checked before the plain "testeur"
# substring it contains.
classify_by_description() {
  d="$1"
  case "$d" in
    *testeur-global*|*"verification globale"*|*"vérification globale"*) echo "testeur-global" ;;
    *orchestrat*) echo "orchestrateur" ;;
    *pessimiste*) echo "pessimiste" ;;
    *candide*) echo "candide" ;;
    *testeur*) echo "testeur" ;;
    *) echo "" ;;
  esac
}

# Fallback: the meta.json's own `agentType` field (not always reliable —
# can read "general-purpose" for any subagent type depending on how it
# was spawned — hence tried only if the description didn't match).
classify_by_agent_type() {
  case "$1" in
    testeur-global) echo "testeur-global" ;;
    pessimiste) echo "pessimiste" ;;
    candide) echo "candide" ;;
    testeur) echo "testeur" ;;
    orchestrateur) echo "orchestrateur" ;;
    worker|general-purpose) echo "worker" ;;
    *) echo "" ;;
  esac
}

while true; do
  now=$(date +%s)
  w=0; te=0; pe=0; ca=0; orc=0; tg=0

  for meta in $(find "$PROJECTS_DIR" -name 'agent-*.meta.json' 2>/dev/null); do
    jsonl="${meta%.meta.json}.jsonl"
    [ -f "$jsonl" ] || continue
    mtime=$(stat -c %Y "$jsonl" 2>/dev/null) || continue
    age=$(( now - mtime ))
    [ "$age" -le "$FRESH_SECONDS" ] || continue

    desc=$(sed -n 's/.*"description":"\([^"]*\)".*/\1/p' "$meta" | head -1)
    desc_lc=$(printf '%s' "$desc" | tr '[:upper:]' '[:lower:]')
    label=$(classify_by_description "$desc_lc")

    if [ -z "$label" ]; then
      atype=$(sed -n 's/.*"agentType":"\([^"]*\)".*/\1/p' "$meta" | head -1)
      label=$(classify_by_agent_type "$atype")
    fi

    case "$label" in
      worker) w=1 ;;
      testeur) te=1 ;;
      pessimiste) pe=1 ;;
      candide) ca=1 ;;
      orchestrateur) orc=1 ;;
      testeur-global) tg=1 ;;
    esac
  done

  tmp="${OUT_FILE}.tmp.$$"
  {
    echo "# HELP claude_agent Proxy signal (1 = transcript activity within ${FRESH_SECONDS}s, 0 = none) per Claude Code subagent type. Not an exact 'LLM call in flight' signal."
    echo "# TYPE claude_agent gauge"
    echo "claude_agent{agent=\"worker\"} $w"
    echo "claude_agent{agent=\"testeur\"} $te"
    echo "claude_agent{agent=\"pessimiste\"} $pe"
    echo "claude_agent{agent=\"candide\"} $ca"
    echo "claude_agent{agent=\"orchestrateur\"} $orc"
    echo "claude_agent{agent=\"testeur-global\"} $tg"
  } > "$tmp"
  mv "$tmp" "$OUT_FILE"

  sleep "$INTERVAL"
done
