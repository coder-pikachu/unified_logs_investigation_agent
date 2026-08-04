#!/usr/bin/env bash
# NOVA 2.0 RCA — guided live demo runner.
#
# Drives the full 5-minute core narrative end-to-end:
#   clean slate -> stack up -> background traffic -> fire scenario (API)
#   -> autonomous incident (Change Streams) -> walk the evidence
#   -> fire again (memory recall beat) -> the `grep embed` beat.
#
# Usage:
#   scripts/demo.sh                 # interactive: pauses at each presenter beat
#   scripts/demo.sh --auto          # unattended: sleeps instead of prompts (rehearsal/CI)
#   scripts/demo.sh --skip-reset    # keep existing incidents/memory (no clean slate)
#   scripts/demo.sh --scenario upi-payment-failures
#
# Env overrides: AGENT_PORT (8000), UI_PORT (5173), RATE (6), TRAFFIC_SECONDS (1200)

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AGENT_PORT="${AGENT_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"
API="http://localhost:${AGENT_PORT}/api"
UI="http://localhost:${UI_PORT}"
RATE="${RATE:-6}"
TRAFFIC_SECONDS="${TRAFFIC_SECONDS:-1200}"
JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21}"
JAR="$ROOT/novasim/target/novasim.jar"
RUN="$ROOT/.run"
PY="$ROOT/.venv/bin/python"

AUTO=0
RESET=1
SCENARIO="eis-martech-brownout"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto) AUTO=1 ;;
    --skip-reset) RESET=0 ;;
    --scenario) SCENARIO="$2"; shift ;;
    *) echo "unknown flag: $1"; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------- ui helpers
C0="\033[0m"; CB="\033[1m"; CC="\033[36m"; CG="\033[32m"; CY="\033[33m"; CR="\033[31m"
say()    { printf "${CC}▸${C0} %s\n" "$*"; }
ok()     { printf "${CG}✓${C0} %s\n" "$*"; }
warn()   { printf "${CY}!${C0} %s\n" "$*"; }
fail()   { printf "${CR}✗ %s${C0}\n" "$*"; exit 1; }
banner() { printf "\n${CB}${CC}══ %s ══${C0}\n" "$*"; }
pause()  {
  if [[ "$AUTO" == "1" ]]; then sleep "${1:-8}"; else
    printf "${CY}  [ENTER to continue]${C0} "; read -r
  fi
}

jsonq() { python3 -c "import sys,json; $1" 2>/dev/null; }

wait_http() { # url, label, timeout_s
  local t=0
  until curl -sf "$1" >/dev/null 2>&1; do
    sleep 1; t=$((t + 1))
    [[ $t -ge ${3:-60} ]] && fail "$2 not reachable after ${3:-60}s ($1)"
  done
  ok "$2 up"
}

incident_count() { curl -s "$API/incidents" | jsonq 'print(len(json.load(sys.stdin)))' || echo 0; }

newest_incident() { # prints "key|status|faultClass|origin|recalled|confidence"
  curl -s "$API/incidents" | jsonq '
d = json.load(sys.stdin)
i = d[0] if d else {}
rca = i.get("rca") or {}
print("|".join(str(x) for x in (
    i.get("incidentKey",""), i.get("status",""), i.get("faultClass",""),
    i.get("originComponent",""), len(i.get("recalledIncidents") or []),
    rca.get("confidence",""))))'
}

wait_incident() { # baseline_count timeout_s -> sets INC_* globals, prints progress
  local base="$1" timeout="${2:-150}" t=0 line="" n
  while true; do
    n=$(incident_count)
    if [[ "$n" -gt "$base" ]]; then
      line=$(newest_incident)
      IFS='|' read -r INC_KEY INC_STATUS INC_FAULT INC_ORIGIN INC_RECALLED INC_CONF <<<"$line"
      [[ "$INC_STATUS" == "complete" || "$INC_STATUS" == "failed" ]] && break
    fi
    sleep 2; t=$((t + 2))
    [[ $((t % 10)) -eq 0 ]] && say "  …waiting (${t}s) — incidents: $n, status: ${INC_STATUS:-–}"
    [[ $t -ge $timeout ]] && { warn "timed out after ${timeout}s (incidents: $n)"; return 1; }
  done
  INC_ELAPSED=$t
  return 0
}

# ---------------------------------------------------------------- preflight
banner "PREFLIGHT"
[[ -f "$ROOT/.env" ]] || fail ".env missing — copy .env.example and fill Atlas/Grove creds"
command -v curl >/dev/null || fail "curl required"
command -v python3 >/dev/null || fail "python3 required"
[[ -x "$JAVA_HOME/bin/java" ]] || fail "Java 21 not found at $JAVA_HOME (set JAVA_HOME)"
[[ -f "$JAR" ]] || { say "building simulator jar…"; make -s build-sim || fail "jar build failed"; }
ok "env + toolchain"

if [[ "$RESET" == "1" ]]; then
  say "clean slate: stopping stack, wiping incidents/memory/checkpoints, reseeding kb…"
  make -s down >/dev/null 2>&1
  make -s reset >/dev/null || fail "reset failed (Atlas reachable?)"
  ok "state reset (memory demo will be reproducible: run #1 cold, run #2 warm)"
else
  warn "skipping reset — memory may already be warm"
fi

say "bringing up agent + UI…"
make -s up >/dev/null || fail "make up failed"
wait_http "$API/health" "agent API" 60
wait_http "$UI" "UI" 60

HEALTH=$(curl -s "$API/health")
echo "$HEALTH" | grep -q '"mongo"' && ok "Atlas connected" || warn "health: $HEALTH"
echo "$HEALTH" | grep -qi 'grove' && ok "Grove LLM reachable" || warn "Grove not confirmed — LLM nodes may fail"

say "starting background traffic (${RATE} journey-actions/s for ${TRAFFIC_SECONDS}s)…"
mkdir -p "$RUN"
JAVA_HOME="$JAVA_HOME" nohup "$JAVA_HOME/bin/java" -jar "$JAR" \
  --headless --rate "$RATE" --duration "$TRAFFIC_SECONDS" \
  >"$RUN/novasim.log" 2>&1 &
SIM_PID=$!
echo "$SIM_PID" >"$RUN/novasim.pid"
sleep 6
kill -0 "$SIM_PID" 2>/dev/null || fail "simulator died — check $RUN/novasim.log"
ok "traffic flowing (pid $SIM_PID; journeys ticking on the ops board)"

# ---------------------------------------------------------------- beat 1
banner "BEAT 1 · LIVE OPS BOARD (~30s)"
(command -v open >/dev/null && open "$UI") || true
cat <<EOF
  Show:  $UI  → OPS BOARD
  Say:   "A live retail-banking super-app: journeys ticking (dashboard, billpay,
          PFM, lending, offers), downstream tiles green — every sparkline is a
          \$percentile aggregation on ONE Atlas time-series collection."
EOF
pause 12

# ---------------------------------------------------------------- beat 2
banner "BEAT 2 · FIRE ${SCENARIO} — NOBODY CLICKS ANALYZE"
BASE_COUNT=$(incident_count)
RES=$(curl -s -X POST "$API/scenarios/$SCENARIO/fire")
echo "$RES" | grep -q '"ok"' && ok "scenario fired: $SCENARIO" || fail "fire failed: $RES"
cat <<'EOF'
  Say:   "The failure is injected at the SOURCE system. No webhook, no cron —
          the agent wakes because the data changed: Change Streams on the audit
          collections. Watch the incident card appear by itself."
  Show:  ops board — the affected tile ambers, error counts tick up.
EOF
T_FIRE=$(date +%s)
say "waiting for the autonomous incident (change stream → debounce → 9-node graph)…"
if wait_incident "$BASE_COUNT" 150; then
  T_INC1=$(date +%s)
  ok "incident ${INC_KEY} — ${INC_STATUS} in ~${INC_ELAPSED}s"
  ok "faultClass=${INC_FAULT} · origin=${INC_ORIGIN} · confidence=${INC_CONF}"
else
  warn "no completed incident yet — check AGENT WORKFLOW tab / .run/agent.log"
  T_INC1=$(date +%s)
fi

# ---------------------------------------------------------------- beat 3
banner "BEAT 3 · WALK THE EVIDENCE (~90s)"
cat <<'EOF'
  Show, in order:
   1. AGENT WORKFLOW  — the DAG lit node by node; click `recall`: both hybrid
      arms + the literal $rankFusion pipeline. Click `verify`: the aggregation
      it actually ran.
   2. INCIDENT DETAIL — swimlanes: the loud journey errors are symptoms; the
      single ◎ ORIGIN marker sits on the shared downstream route.
   3. "Agent queries · MongoDB" panel — every query the investigation fired,
      in execution order: indexed finds (correlation joins), the TIME SERIES
      $percentile baseline, $rankFusion hybrid recall, verify aggregations.
   4. Click an evidence chip — the exact audit document opens in Raw logs.
  Say:   "The RCA names an origin that is NOT the service that screamed —
          and every claim is a clickable document, not prose."
EOF
pause 20

# ---------------------------------------------------------------- beat 4
banner "BEAT 4 · FIRE IT AGAIN — MEMORY"
# stay outside the 120s cascade-merge window so run #2 is a NEW incident
GAP=$(( $(date +%s) - T_INC1 ))
if [[ $GAP -lt 135 ]]; then
  say "holding $((135 - GAP))s (merge window: a re-fire inside 120s would join incident #1)…"
  sleep $((135 - GAP))
fi
BASE_COUNT=$(incident_count)
RES=$(curl -s -X POST "$API/scenarios/$SCENARIO/fire")
echo "$RES" | grep -q '"ok"' && ok "scenario re-fired" || warn "fire failed: $RES"
cat <<'EOF'
  Say:   "Same failure, second time. Now the agent REMEMBERS: hybrid recall over
          incident_memory — embedded and synced inside Atlas by Automated
          Embedding (voyage). No embedding API call anywhere in this codebase."
EOF
if wait_incident "$BASE_COUNT" 150; then
  ok "incident ${INC_KEY} — ${INC_STATUS} in ~${INC_ELAPSED}s"
  if [[ "${INC_RECALLED:-0}" -gt 0 ]]; then
    ok "recalled prior incidents: ${INC_RECALLED} · confidence=${INC_CONF} (warm path)"
  else
    warn "no recall recorded — check MEMORY tab (autoEmbed sync can lag ~1 min after run #1)"
  fi
  say "show: MEMORY tab — the route playbook's hit count incremented."
else
  warn "second incident not completed in time — narrate from the MEMORY tab"
fi
pause 10

# ---------------------------------------------------------------- beat 5
banner "BEAT 5 · THE GREP — NO EMBEDDING CLIENT"
say "\$ make check-no-embed"
make -s check-no-embed && ok "no embedding client in /agent — Atlas Automated Embedding does it in-database"
pause 8

# ---------------------------------------------------------------- wrap
banner "DEEP-DIVE POINTERS (15-min architect track — see docs/DEMO.md)"
cat <<EOF
  · autoEmbed index:      atlas/index_defs/incident_memory_vector.json (model voyage-4-lite)
  · time series:          service_metrics — granularity "minutes", secondary index {meta.service, ts}
  · checkpoints:          LangGraph MongoDBSaver docs in the 'checkpoints' collection
  · verify pipeline:      any incident → AGENT WORKFLOW → verify node inspector
  · offline fallback:     make replay   (recorded run, zero network)

  Background traffic keeps running (pid $SIM_PID, ~${TRAFFIC_SECONDS}s total).
  Stop it:   kill \$(cat .run/novasim.pid)
  Full stop: make down
EOF
if [[ "$AUTO" == "1" ]]; then
  say "auto mode: stopping background traffic"
  kill "$SIM_PID" 2>/dev/null
fi
ok "demo script complete"
