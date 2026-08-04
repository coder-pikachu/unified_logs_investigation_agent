#!/usr/bin/env bash
# NOVA 2.0 RCA — guided demo for the CHAT-BASED investigation (INVESTIGATE tab).
#
# Five beats, each proving a distinct chat behavior:
#   1. HONESTY      — ask about a healthy journey -> "no matching failures", no hallucination
#   2. AUTONOMOUS   — fire a scenario; the watcher builds the incident (context for beat 3)
#   3. MATCH        — describe the issue in plain words -> triage joins evidence to the
#                     existing incident and cites its RCA (incidentKey linked)
#   4. FOLLOW-UP    — same session: "who was affected? what should we do?" -> converse
#                     over the linked incident
#   5. VISION       — post a screenshot (data URL) -> vision LLM triages the image itself
#   6. CHAT-LAUNCH  — ask about noise-floor failures the watcher deliberately ignores
#                     -> chat claims its own incident and replies when the RCA lands
#
# Usage:
#   scripts/demo_chat.sh            # interactive: presenter types in the UI; script cues + fires
#   scripts/demo_chat.sh --auto     # unattended: drives POST /api/chat and asserts on replies
#   scripts/demo_chat.sh --fresh    # force clean slate (down -> reset -> up) first
#
# Default is to REUSE a running stack (this demo is usually act II after scripts/demo.sh).

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
SCENARIO="${SCENARIO:-eis-martech-brownout}"

AUTO=0
FRESH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto) AUTO=1 ;;
    --fresh) FRESH=1 ;;
    *) echo "unknown flag: $1"; exit 2 ;;
  esac
  shift
done

C0="\033[0m"; CB="\033[1m"; CC="\033[36m"; CG="\033[32m"; CY="\033[33m"; CR="\033[31m"
say()    { printf "${CC}▸${C0} %s\n" "$*"; }
ok()     { printf "${CG}✓${C0} %s\n" "$*"; }
warn()   { printf "${CY}!${C0} %s\n" "$*"; }
fail()   { printf "${CR}✗ %s${C0}\n" "$*"; exit 1; }
banner() { printf "\n${CB}${CC}══ %s ══${C0}\n" "$*"; }
pause()  {
  if [[ "$AUTO" == "1" ]]; then sleep "${1:-6}"; else
    printf "${CY}  [ENTER to continue]${C0} "; read -r
  fi
}

# chat_post MESSAGE [SESSION_ID] [IMAGE_FILE] -> sets CHAT_SID, CHAT_KEY, CHAT_TEXT
chat_post() {
  local out
  out=$(MSG="$1" SID="${2:-}" IMG="${3:-}" API="$API" python3 - <<'PY'
import base64, json, os, sys, urllib.request
body = {"message": os.environ["MSG"]}
if os.environ.get("SID"):
    body["sessionId"] = os.environ["SID"]
if os.environ.get("IMG"):
    raw = open(os.environ["IMG"], "rb").read()
    body["image"] = "data:image/png;base64," + base64.b64encode(raw).decode()
req = urllib.request.Request(os.environ["API"] + "/chat",
                             data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
try:
    d = json.load(urllib.request.urlopen(req, timeout=90))
except Exception as e:
    print(f"ERROR\x1f\x1f{e}"); sys.exit(0)
text = ((d.get("reply") or {}).get("text") or "").replace("\n", " ⏎ ")
print("\x1f".join((d.get("sessionId", ""), d.get("incidentKey") or "", text)))
PY
)
  # \x1f (unit separator): tab is IFS *whitespace* — consecutive tabs collapse,
  # which swallowed the empty incidentKey field and shifted text into CHAT_KEY.
  IFS=$'\x1f' read -r CHAT_SID CHAT_KEY CHAT_TEXT <<<"$out"
  [[ "$CHAT_SID" == "ERROR" ]] && { warn "chat call failed: $CHAT_TEXT"; return 1; }
  return 0
}

show_reply() { printf "  ${CB}agent:${C0} %s\n" "$(echo "$CHAT_TEXT" | cut -c1-500)"; }

incident_count() {
  curl -s "$API/incidents" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0
}

wait_incident() { # baseline timeout
  local base="$1" timeout="${2:-150}" t=0 st=""
  while true; do
    if [[ "$(incident_count)" -gt "$base" ]]; then
      st=$(curl -s "$API/incidents" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('status','') if d else '')" 2>/dev/null)
      [[ "$st" == "complete" || "$st" == "failed" ]] && return 0
    fi
    sleep 2; t=$((t + 2))
    [[ $((t % 10)) -eq 0 ]] && say "  …waiting (${t}s) — status: ${st:-–}"
    [[ $t -ge $timeout ]] && return 1
  done
}

wait_chat_rca() { # session_id timeout -> waits for the async "RCA complete" turn
  local sid="$1" timeout="${2:-150}" t=0 txt=""
  while true; do
    txt=$(curl -s "$API/chat/$sid" | python3 -c '
import sys, json
d = json.load(sys.stdin) or {}
for m in reversed(d.get("messages") or []):
    t = m.get("text") or ""
    if "RCA complete" in t or "investigation failed" in t.lower():
        print(t.replace("\n", " ⏎ ")[:500]); break
' 2>/dev/null)
    [[ -n "$txt" ]] && { CHAT_TEXT="$txt"; return 0; }
    sleep 3; t=$((t + 3))
    [[ $((t % 15)) -eq 0 ]] && say "  …investigating (${t}s) — watch AGENT WORKFLOW"
    [[ $t -ge $timeout ]] && return 1
  done
}

# ---------------------------------------------------------------- preflight
banner "PREFLIGHT"
[[ -f "$ROOT/.env" ]] || fail ".env missing — copy .env.example and fill Atlas/Grove creds"

if [[ "$FRESH" == "1" ]]; then
  say "fresh slate requested: down -> reset -> up…"
  make -s down >/dev/null 2>&1
  make -s reset >/dev/null || fail "reset failed"
fi
if ! curl -sf "$API/health" >/dev/null 2>&1; then
  say "stack not running — bringing it up…"
  make -s up >/dev/null || fail "make up failed"
  local_t=0
  until curl -sf "$API/health" >/dev/null 2>&1; do
    sleep 1; local_t=$((local_t + 1)); [[ $local_t -ge 60 ]] && fail "agent not reachable"
  done
fi
ok "agent API up"
curl -sf "$UI" >/dev/null 2>&1 && ok "UI up" || warn "UI not reachable at $UI"

if [[ -f "$RUN/novasim.pid" ]] && kill -0 "$(cat "$RUN/novasim.pid")" 2>/dev/null; then
  ok "background traffic already flowing (pid $(cat "$RUN/novasim.pid"))"
else
  [[ -f "$JAR" ]] || { say "building simulator jar…"; make -s build-sim || fail "jar build failed"; }
  say "starting background traffic (${RATE}/s for ${TRAFFIC_SECONDS}s)…"
  mkdir -p "$RUN"
  JAVA_HOME="$JAVA_HOME" nohup "$JAVA_HOME/bin/java" -jar "$JAR" \
    --headless --rate "$RATE" --duration "$TRAFFIC_SECONDS" >"$RUN/novasim.log" 2>&1 &
  echo $! >"$RUN/novasim.pid"
  sleep 6
  kill -0 "$(cat "$RUN/novasim.pid")" 2>/dev/null || fail "simulator died — see $RUN/novasim.log"
  ok "traffic flowing"
fi
(command -v open >/dev/null && open "$UI") || true

# ---------------------------------------------------------------- beat 1
banner "BEAT 1 · HONESTY — ASK ABOUT A HEALTHY JOURNEY"
MSG1="Customers report billpay autopay is failing. Can you check?"
cat <<EOF
  Show:  INVESTIGATE tab.
  Type:  "$MSG1"
  Say:   "Nothing is wrong with billpay. The agent searches 30 minutes of audit
          logs — and says so, listing what it DOES monitor. No hallucinated RCA."
EOF
if [[ "$AUTO" == "1" ]]; then
  chat_post "$MSG1" && show_reply
  echo "$CHAT_TEXT" | grep -qi "no matching failures" \
    && ok "honest no-match confirmed (incidentKey: none)" \
    || warn "expected a no-match reply — got: $(echo "$CHAT_TEXT" | cut -c1-120)"
fi
pause 8

# ---------------------------------------------------------------- beat 2
banner "BEAT 2 · CONTEXT — FIRE ${SCENARIO} (WATCHER BUILDS THE INCIDENT)"
BASE=$(incident_count)
curl -s -X POST "$API/scenarios/$SCENARIO/fire" | grep -q '"ok"' \
  && ok "scenario fired" || fail "fire failed"
say "waiting for the autonomous incident (Change Streams — nobody clicks anything)…"
wait_incident "$BASE" 150 && ok "incident complete" || warn "incident not complete yet — beats 3-5 may launch instead of match"

# ---------------------------------------------------------------- beat 3
banner "BEAT 3 · MATCH — DESCRIBE THE ISSUE IN PLAIN WORDS"
MSG3="Users say the offers section on the app dashboard is broken and personalized offers will not load."
cat <<EOF
  Type:  "$MSG3"
  Say:   "No error code given. The LLM triages the complaint into journeys from
          the catalog, a deterministic ladder finds the failing transactions,
          joins them to the incident the watcher already built — and cites its
          root cause. Click the chip: it opens that exact incident."
EOF
SESSION=""
if [[ "$AUTO" == "1" ]]; then
  chat_post "$MSG3" && show_reply
  SESSION="$CHAT_SID"
  if [[ -n "$CHAT_KEY" ]]; then
    ok "linked incident: $CHAT_KEY"
  else
    warn "no incident linked — reply above"
  fi
fi
pause 10

# ---------------------------------------------------------------- beat 4
banner "BEAT 4 · FOLLOW-UP — SAME CONVERSATION"
MSG4="Who was affected and what should we do about it?"
cat <<EOF
  Type:  "$MSG4"   (same chat session)
  Say:   "Multi-turn: the session lives in Atlas ('chat_sessions', 7-day TTL) —
          the support conversation is on the same platform as the logs it
          discusses. The answer comes from the linked incident document:
          blast radius, mitigation tiers."
EOF
if [[ "$AUTO" == "1" && -n "$SESSION" ]]; then
  chat_post "$MSG4" "$SESSION" && show_reply
  [[ -n "$CHAT_TEXT" && "$CHAT_TEXT" != "ERROR" ]] && ok "follow-up answered in-session"
fi
pause 10

# ---------------------------------------------------------------- beat 5
banner "BEAT 5 · VISION — TRIAGE A SCREENSHOT"
cat <<'EOF'
  Do:    screenshot the ambered Offers tile (or a user's error screen) and drag
         it into the chat with just: "a user sent this — what's going on?"
  Say:   "A vision LLM reads the screenshot itself — journey names, error codes,
          ids — and runs the same evidence ladder. The image is stored in Atlas
          ('chat_images', TTL'd), served back into the conversation."
EOF
if [[ "$AUTO" == "1" ]]; then
  IMG=$(python3 - <<'PY'
try:
    from PIL import Image, ImageDraw
except ImportError:
    print(""); raise SystemExit
img = Image.new("RGB", (720, 280), "#101418")
d = ImageDraw.Draw(img)
d.text((30, 30), "NOVA App — Dashboard", fill="#e8eaed")
d.text((30, 90), "Offers unavailable", fill="#f28b82")
d.text((30, 130), "We could not load your personalized offers.", fill="#e8eaed")
d.text((30, 170), "Error: TEEIS009 (offers_fetch)", fill="#f28b82")
p = "/tmp/nova_chat_screenshot.png"
img.save(p)
print(p)
PY
)
  if [[ -n "$IMG" ]]; then
    chat_post "a user sent this screenshot — what's going on?" "" "$IMG" && show_reply
    [[ -n "$CHAT_KEY" ]] && ok "vision triage linked incident: $CHAT_KEY" \
                         || warn "vision triage found no link — reply above"
  else
    warn "PIL not available — skipping synthetic screenshot (do this beat manually)"
  fi
fi
pause 10

# ---------------------------------------------------------------- beat 6
banner "BEAT 6 · CHAT-LAUNCHED INVESTIGATION — BELOW THE WATCHER'S THRESHOLD"
MSG6="A customer complains their pre-approved personal loan offer keeps getting rejected in the app."
cat <<EOF
  Type:  "$MSG6"
  Say:   "Single-user business rejections are the noise floor — the watcher
          deliberately does NOT page on them. But a human asked. The chat claims
          its own incident (same idempotent path as the watcher), runs the full
          9-node graph, and replies here when the RCA lands. Watch AGENT
          WORKFLOW light up — a human question and a change stream are just
          two doors into the same investigation."
  Tip:   cleanest on a quiet board — if a scenario fired in the last few
         minutes, its error storm can dominate the widened correlation window
         and blend into this RCA. Live: run this beat first or ~5 min later.
EOF
if [[ "$AUTO" == "1" ]]; then
  chat_post "$MSG6" && show_reply
  if echo "$CHAT_TEXT" | grep -q "Investigating"; then
    ok "chat claimed incident: ${CHAT_KEY:-?} — waiting for the RCA to land in-session…"
    wait_chat_rca "$CHAT_SID" 180 \
      && { ok "RCA landed in chat:"; show_reply; } \
      || warn "RCA did not land within 180s — check AGENT WORKFLOW / agent log"
  elif echo "$CHAT_TEXT" | grep -qi "no matching failures"; then
    warn "no papl noise in the lookback window yet (traffic too young) — re-ask after ~2 min"
  else
    warn "evidence already covered by an incident — still a valid beat (reply above)"
  fi
fi
pause 8

# ---------------------------------------------------------------- wrap
banner "WRAP — WHAT THIS PROVED"
cat <<EOF
  · One pipeline, two doors: change stream (autonomous) and human chat both run
    the same 9-node LangGraph — same evidence, same inspectable queries.
  · Honest by construction: no evidence -> no RCA, and it says so.
  · The conversation itself is on Atlas: chat_sessions + chat_images (TTL),
    replies streamed over the same SSE bus the DAG uses.
  Deep dive: docs/DEMO.md · agent/nova_agent/api/chat.py (triage ladder is
  deterministic; Atlas Search fallback fires ONLY without structured signal).
EOF
ok "chat demo script complete"
