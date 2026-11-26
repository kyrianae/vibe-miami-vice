#!/bin/sh
# Writes 2 Prometheus textfile metrics per known Claude Code subagent
# type, based on ~/.claude/projects/*/subagents/ transcripts (mounted
# read-only) — no LLM call, pure filesystem inspection:
#
#   claude_agent{agent="<type>"} 0|1
#     Proxy for "currently working": 1 if at least one instance of this
#     type has a transcript modified within FRESH_SECONDS, else 0. Not an
#     exact "LLM call in flight" signal — a recency heuristic.
#
#   claude_agent_tokens_total{agent="<type>"} <cumulative output tokens>
#     Sum of every assistant message's `message.usage.output_tokens`
#     across ALL transcripts classified as this type (not just fresh
#     ones) — a monotonically growing counter as new agent runs add
#     messages, suitable for rate()/increase() in Grafana/PromQL. Does
#     NOT include input/cache tokens (those aren't newly generated
#     content) — an approximation of "tokens produced by this agent",
#     not the harness's own internal accounting.
#
#   claude_agent{agent="main"} 0|1
#     Same activity proxy, but for the top-level interactive session
#     itself (not a dispatched subagent) — its own transcript lives
#     directly under a project directory (`*.jsonl`), not under
#     `subagents/`. Covers the gap where the main session is actively
#     reading/editing/answering while no subagent happens to be running.
#
#   claude_current_task{task="<description>", agent="<type>"} 1
#     Single row naming the plan task currently in flight — the raw
#     `description` field of the freshest active agent (preferring an
#     `orchestrateur` instance if one is fresh, since its description
#     usually names the plan action directly, e.g. "Orchestrate action
#     3: illustrated demo docs"), else the most recently modified fresh
#     agent of any type. `agent` names which of the 7 types (6 subagent
#     roles + "main") that task belongs to, so a Grafana table/panel can
#     group or color by agent. If no subagent is fresh but the main
#     session itself is (see `claude_agent{agent="main"}` above) — no
#     dispatch, no `description` field to read — falls back to a generic
#     "Session principale (interactif)" label rather than "en attente"
#     (bug found 2026-11-26 : the dashboard showed "en attente" while the
#     main session was visibly active, because this fallback only ever
#     looked at subagent metadata). "en attente"/"none" only when
#     NOTHING (subagent or main) is fresh. Exists so the dashboard shows
#     something readable immediately, not just a 0/1 grid — label
#     cardinality grows over time as task text changes (acceptable at
#     this project's scale, not meant for a high-churn environment).
#
# Runs forever, rewriting the file every INTERVAL seconds (atomic
# write: temp file + rename).
set -eu

PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-/claude-projects}"
OUT_FILE="${OUT_FILE:-/metrics/claude_agents.prom}"
FRESH_SECONDS="${FRESH_SECONDS:-20}"
INTERVAL="${INTERVAL:-15}"

# jq is needed to sum output_tokens across a transcript reliably
# (grep/sed would double count or miss nested usage blocks). Installed
# once at container start, not on every loop iteration.
command -v jq >/dev/null 2>&1 || apk add --no-cache jq >/dev/null 2>&1

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

# Prometheus label value: escape backslash then double-quote.
escape_label() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

while true; do
  now=$(date +%s)
  w=0; te=0; pe=0; ca=0; orc=0; tg=0
  tok_w=0; tok_te=0; tok_pe=0; tok_ca=0; tok_orc=0; tok_tg=0
  best_desc=""; best_is_orch=0; best_mtime=0; best_label=""

  for meta in $(find "$PROJECTS_DIR" -name 'agent-*.meta.json' 2>/dev/null); do
    jsonl="${meta%.meta.json}.jsonl"
    [ -f "$jsonl" ] || continue

    desc=$(sed -n 's/.*"description":"\([^"]*\)".*/\1/p' "$meta" | head -1)
    desc_lc=$(printf '%s' "$desc" | tr '[:upper:]' '[:lower:]')
    label=$(classify_by_description "$desc_lc")

    if [ -z "$label" ]; then
      atype=$(sed -n 's/.*"agentType":"\([^"]*\)".*/\1/p' "$meta" | head -1)
      label=$(classify_by_agent_type "$atype")
    fi
    [ -n "$label" ] || continue

    # Activity gauge: only counts if recently modified.
    mtime=$(stat -c %Y "$jsonl" 2>/dev/null) || mtime=0
    age=$(( now - mtime ))
    if [ "$age" -le "$FRESH_SECONDS" ]; then
      case "$label" in
        worker) w=1 ;;
        testeur) te=1 ;;
        pessimiste) pe=1 ;;
        candide) ca=1 ;;
        orchestrateur) orc=1 ;;
        testeur-global) tg=1 ;;
      esac

      is_orch=0
      [ "$label" = "orchestrateur" ] && is_orch=1
      if [ -z "$best_desc" ] \
        || { [ "$is_orch" -eq 1 ] && [ "$best_is_orch" -eq 0 ]; } \
        || { [ "$is_orch" -eq "$best_is_orch" ] && [ "$mtime" -gt "$best_mtime" ]; }; then
        best_desc="$desc"
        best_is_orch="$is_orch"
        best_mtime="$mtime"
        best_label="$label"
      fi
    fi

    # Token counter: summed over the whole transcript, every cycle
    # (cumulative across this agent's full history on disk, not just
    # the fresh window above).
    file_tokens=$(jq -s '[.[] | .message.usage.output_tokens? // 0] | add // 0' "$jsonl" 2>/dev/null) || file_tokens=0
    case "$label" in
      worker) tok_w=$((tok_w + file_tokens)) ;;
      testeur) tok_te=$((tok_te + file_tokens)) ;;
      pessimiste) tok_pe=$((tok_pe + file_tokens)) ;;
      candide) tok_ca=$((tok_ca + file_tokens)) ;;
      orchestrateur) tok_orc=$((tok_orc + file_tokens)) ;;
      testeur-global) tok_tg=$((tok_tg + file_tokens)) ;;
    esac
  done

  # Top-level session(s): any *.jsonl directly under a project dir
  # (not inside subagents/) with a recent mtime. Deliberately not
  # folded into the loop above — no sibling .meta.json, no
  # description/classification to do, just a freshness check.
  main=0
  for session_jsonl in $(find "$PROJECTS_DIR" -maxdepth 2 -name '*.jsonl' 2>/dev/null); do
    mtime=$(stat -c %Y "$session_jsonl" 2>/dev/null) || continue
    age=$(( now - mtime ))
    if [ "$age" -le "$FRESH_SECONDS" ]; then
      main=1
      break
    fi
  done

  if [ -z "$best_desc" ]; then
    task_label="en attente"
    task_agent="none"
  else
    task_label=$(escape_label "$best_desc")
    task_agent="$best_label"
  fi

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
    echo "claude_agent{agent=\"main\"} $main"
    echo "# HELP claude_agent_tokens_total Cumulative output tokens generated, summed across all transcripts on disk for this agent type. Approximation (output tokens only, not input/cache) — use rate()/increase() for a tokens/s view."
    echo "# TYPE claude_agent_tokens_total counter"
    echo "claude_agent_tokens_total{agent=\"worker\"} $tok_w"
    echo "claude_agent_tokens_total{agent=\"testeur\"} $tok_te"
    echo "claude_agent_tokens_total{agent=\"pessimiste\"} $tok_pe"
    echo "claude_agent_tokens_total{agent=\"candide\"} $tok_ca"
    echo "claude_agent_tokens_total{agent=\"orchestrateur\"} $tok_orc"
    echo "claude_agent_tokens_total{agent=\"testeur-global\"} $tok_tg"
    echo "# HELP claude_current_task Plan task currently in flight (raw agent description, 'en attente'/'none' if idle), labeled with which agent type it belongs to. Label cardinality grows over time as task text changes."
    echo "# TYPE claude_current_task gauge"
    echo "claude_current_task{task=\"$task_label\",agent=\"$task_agent\"} 1"
  } > "$tmp"
  mv "$tmp" "$OUT_FILE"

  sleep "$INTERVAL"
done
