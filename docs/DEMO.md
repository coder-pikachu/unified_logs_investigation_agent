# DEMO.md — NOVA 2.0 RCA on MongoDB Atlas

Four tracks: the **5-minute core** (build backwards from the 90-second narrative), the **15-minute
architect deep-dive**, the **manual scenario playbook** (all 10 injectable failures, step by step), and
the **manual chat investigation**. Audience: architects and builders. One datastore on screen the whole
time.

**One-command guided run:** `make demo-live` (`scripts/demo.sh`) executes the whole 5-minute core —
clean slate → stack up → background traffic → fires the scenario over the API → waits on the autonomous
incident → holds out of the 120s merge window → re-fires for the memory beat → `grep embed` beat —
pausing at each presenter cue (`--auto` for unattended rehearsal, `--scenario <id>` to swap the story).

**Chat-investigation track:** `make demo-chat` (`scripts/demo_chat.sh`) — six beats on the INVESTIGATE
tab: honest no-match → autonomous incident (context) → plain-words match with cited RCA → in-session
follow-up (blast radius, actions) → screenshot vision triage → chat-**launched** investigation of
noise-floor failures the watcher deliberately ignores (RCA lands back in the conversation). Reuses a
running stack by default (act II after `demo-live`); `--fresh` for a clean slate, `--auto` to rehearse.

## Prerequisites (once)
- `.env` filled (repo root, gitignored): `MONGODB_URI`, `GROVE_BASE_URL`, `GROVE_API_KEY`, `ATLAS_*`.
  Collections + indexes are already provisioned; `make atlas-provision` re-verifies them (idempotent).
- Java 21 + Maven on PATH for the simulator (`JAVA_HOME=/opt/homebrew/opt/openjdk@21`).

## Start (under a minute)
```bash
make reset      # clean board: clears incidents/memory/store/checkpoints + audit, reseeds kb_docs
make up         # agent (:8000) + UI (:5173), waits for health
make sim        # interactive simulator — leave this terminal focused for the demo
```
Open **http://localhost:5173** (`make demo` opens it for you). Header should read `SSE stream live ·
MONGO up · GROVE up`. Background traffic ticks the journey tiles; latency sparklines flow from the
`service_metrics` time-series collection.

---

## Track 1 — 5-minute core narrative

**Beat 0 (say):** "Everything on this screen is one MongoDB Atlas database. No Kafka, no Redis, no
Elasticsearch, no external vector DB, no embedding service. Watch."

**Beat 1 — fire the cascade.** In the `make sim` terminal:
```
nova> fire eis-martech-brownout
```
(You may also click the *EIS·MarTech brownout* button on the Ops board — it routes through the same
`agent_state` command the CLI honors.)

**Beat 2 — the board reacts (~seconds).** The **Offers** journey tile ambers, the **MARTECH/EIS** tiles
climb, the `eis_marTech_getInteractOffers` latency sparkline ramps from ~300ms toward ~10s, `TEEIS009
Response Transformation failed` and `martech_hyper-personalization_offers_fetch` errors surface across
multiple sessions in the log firehose. **Nobody clicked anything in the agent** — say: "That incident card
just appeared on its own. That's a **Change Stream** waking the agent, not a poller."

**Beat 3 — watch it think (Agent Workflow tab).** The DAG lights node by node:
`intake → collect → correlate → recall → hypothesize → verify → rca → recommend → persist`. Each node wears
the capability it used: **intake** "Change Streams", **collect** "Time Series", **correlate**
"layered-status decode", **recall** "$rankFusion — Atlas Search + Vector Search (autoEmbed voyage-4-lite)",
**persist** "Automated Embedding — no client code". A live token/cost meter ticks. Say: "`recall` reports
**no similar prior incidents — hybrid search returned 0 above threshold**. First time we've seen this."

**Beat 4 — the RCA lands (Incident Detail tab, ~15–25s in).** Swimlanes show the cross-collection join;
the **ORIGIN** marker sits on the shared EIS route, distinct from the loud `BS000001` journey symptoms.
Say the money line: **"The user-facing offer failures across N sessions are symptoms. The origin is the
shared EIS `thirdParty/wrapper/Martech` route, whose response transformation began failing — and here are
the exact audit documents, clickable."** Click an evidence chip → the raw-logs panel jumps to that `_id`.
Recommendations: immediate (circuit-break the offers widget), fix (EIS transformation config for the
Martech contract), prevention (latency + `TEEIS009`-rate alert on the route).

**Beat 5 — memory (fire again).**
```
nova> fire eis-martech-brownout
```
This run **recall hits**: the previous incident and its playbook surface, the DAG **short-circuits**
(`recall → confirm → persist`, skipping the LLM hypothesize/verify), the RCA is confirmed in a fraction of
the time with higher confidence, and the Memory tab shows the playbook **hit count = 2**. Say: "Second time,
the agent remembers — faster, more confident, citing the first incident. That memory is native Atlas."

---

## Track 2 — 15-minute architect deep-dive

Do the 5-minute core first, then open the hood. All of this is one database.

1. **`grep -r embed` beat (scripted).** In a terminal:
   ```bash
   grep -rin "embed" agent/        # → no embedding client anywhere
   grep -rin "autoEmbed" atlas/    # → the word lives only in index-definition JSON
   ```
   Say: "The app never calls an embedding API. Atlas embeds `summary_text` and `body` at write time and at
   query time — **Automated Embedding**, `voyage-4-lite`, inside the database."

2. **The `autoEmbed` index definition.** Open `atlas/index_defs/incident_memory_vector.json` (and
   `kb_docs_vector.json`): `{"type":"autoEmbed","path":"summary_text","model":"voyage-4-lite"}`. In the
   Atlas UI, show the same index on the cluster. Note embeddings are stored in the internal
   `__mdb_internal_search` collection — never written by app code.

3. **The hybrid `$rankFusion` pipeline (Agent Workflow → click `recall`).** The inspector prints the
   **literal aggregation**: one `$rankFusion` per collection, a `$vectorSearch` arm with
   `query:{text:…}` (no `queryVector`) and a `$search` lexical arm keyed on exact `err_cd`/`srvc_id`
   tokens, fused with `scoreDetails`. The side panel shows **both arms and the fused ranking**. Say:
   "Error codes like `TEEIS009` are exact tokens — lexical. 'Downstream transformation failures during
   offer fetch' is semantic — vector. `$rankFusion` combines them."

4. **A verify node's real pipeline (click `verify`).** The inspector shows the **actual aggregation the
   agent ran** to test its leading hypothesis — the incidence check (distinct `usr_id` on the route in the
   window) and the ops/config precursor scan. Not a prompt trick: deterministic MongoDB.

5. **LangGraph checkpoints (mongosh / Compass).**
   ```
   use nova_rca
   db.checkpoints.find().sort({_id:-1}).limit(1)      // MongoDBSaver — short-term thread state
   db.store.find({}, {value:1})                        // MongoDBStore — cross-thread playbooks
   ```
   Say: "The agent's memory — both the LangGraph checkpointer and the long-term store — are Atlas
   collections. No external memory service."

6. **The time-series collection.**
   ```
   db.getCollectionInfos({name:"service_metrics"})     // timeField ts, metaField meta, granularity seconds
   ```
   These power the ops-board sparklines and the agent's p95 baseline-vs-incident check. Note: Change
   Streams don't run on time-series collections — that's why triggers sit on the audit collections.

7. **Cross-collection correlation.** In Incident Detail, walk the swimlanes: three audit collections joined
   on `trns_id`/`sessn_tkn_id`, the origin on a downstream route, the loud errors as journey-side symptoms.
   Optionally show the layered-status trap: `unipay-bbps-brownout` has `trns_sts:'success'` with a
   business-failure payload (`responseReason:"Failure"`, `BFR003`) — the agent classifies transport **and**
   business status, so it isn't fooled.

---

## Track 3 — manual scenario playbook (all 10)

Every scenario follows the same five-step rhythm; the per-scenario notes below tell you what is
*different* — the on-board signals, the decoy, the origin the RCA must name, and the line to say.

**The universal rhythm:**
1. **Fire** — in the `make sim` terminal: `nova> fire <id>` (or expand the scenario's card in the
   Ops-board catalog and click fire — same `agent_state` command path).
2. **Board reacts** (seconds) — narrate the tiles/sparklines/firehose while the effects build.
3. **Incident appears by itself** — say the Change-Streams line; switch to **Agent Workflow** and let
   the DAG light up (~15–30s to a complete RCA).
4. **Incident Detail** — swimlanes (ORIGIN vs symptoms), *Collections analyzed*, *Agent queries ·
   MongoDB* panel, click one evidence chip to the raw document.
5. **Optional memory beat** — re-fire the *same* scenario **at least 2 minutes later** (inside 120s it
   merges into the open cascade instead of creating a run #2). `recall` then cites run #1: faster,
   higher confidence, playbook hit count increments. Works for any scenario.

Confidence is honest, not cosmetic — expect **~0.8** on the clean single-route stories, **~0.45–0.65**
on layered/desync stories, and **deliberately low (~0.2–0.3)** where the evidence is genuinely thin
(poison loop, gateway-wide blast). Low confidence on the right answer is a feature; narrate it.

| # | `fire <id>` | Fault | Effects | The story in one line |
|---|---|---|---|---|
| 1 | `login-failures` | technical | 60s | IAM behind login dies; a wall of failed logins is the symptom |
| 2 | `upi-payment-failures` | technical | 60s | UPI switch times out (U68); failed payments are the symptom |
| 3 | `eis-martech-brownout` | technical | 30s | Shared EIS Martech route degrades (TEEIS009, ~10s) |
| 4 | `martech-cif-desync` | business | 30s | A *successful* ops job caused the failures |
| 5 | `think360-token-expiry` | technical | 30s | One expired credential fans out across all PFM journeys |
| 6 | `unipay-bbps-brownout` | business | 180s | Business brownout with **no red status field anywhere** |
| 7 | `gsa-validation-hang` | technical | 30s | Dependency latency, not the validation code |
| 8 | `demand-loan-improper-response` | technical | 30s | The innermost nested error code is the real cause |
| 9 | `poison-retry-loop` | technical | 20s | Loud error count, one user — incidence beats volume |
| 10 | `eis-gateway-pool-exhaustion` | technical | 40s | Everything EIS fails at once — blame the shared gateway |

### 1. `login-failures` — "User can't log in"
- **Watch:** Login journey tile reddens; `eis_iam_authenticate` error-rate/latency spike in the
  sparklines; `5151` login failures across many users in the firehose.
- **Trap → truth:** a wall of failed logins looks like an app problem → origin is the **one shared IAM
  route** on the EIS gateway (`TEIAM001`, `trns_sts -2`); every customer report is a symptom.
- **Say:** "Fifty users can't log in. Zero of them are the problem. One shared identity route is."

### 2. `upi-payment-failures` — "UPI payments failing"
- **Watch:** UPI journey tile; `unipay_upi_payment_transfer` latency ramp ~240ms → 8s in the metrics;
  `5151` payment failures piling up per user.
- **Trap → truth:** looks like a wallet/app bug → origin is the **UPI switch route at UNIPAY** timing
  out with NPCI-style `U68`.
- **Say:** "Every failed payment on a phone screen traces to one switch route behind UNIPAY."

### 3. `eis-martech-brownout` — the flagship (this is Track 1)
- **Watch:** Offers tile ambers; `eis_marTech_getInteractOffers` p95 ~300ms → ~10s; `TEEIS009
  Response Transformation failed` counts tick; `BS000001`/`BSYHP003` offer errors across sessions.
- **Trap → truth:** loud dashboard business errors on many users → origin is the **shared EIS
  `thirdParty/wrapper/Martech` route** whose response transformation fails.
- **Show:** the `verify` inspector — the incidence aggregation (distinct users on the route) that
  separates systemic from single-user.
- **Say:** the Track-1 Beat-4 money line.

### 4. `martech-cif-desync` — the success document that caused it
- **Watch:** `BSYHP003 "CIF Is Not Recognized By Martech"` spikes for a cohort; **EIS latency stays
  normal** — no `TEEIS009`, no p95 blowout. Deliberately quiet on the metrics.
- **Trap → truth:** a business-error spike with a healthy backend → origin is the **ops "Martech
  audience refresh" transaction — a `success` document** ~45s before the first failure, which dropped
  CIFs from the audience store.
- **Show:** Incident Detail timeline — the ORIGIN marker sits on a *green* ops transaction that
  precedes every red symptom. This is the "correlation beats grep" scenario: no error-log search
  finds a success doc.
- **Say:** "The root cause never logged an error. The agent linked a *successful* change to the
  failures that followed it."

### 5. `think360-token-expiry` — one credential, many journeys
- **Watch:** PFM tiles (kyc / consent / summary) fail together; `eis_financialfitness_accessToken`
  failures; fast-fail signature — single-digit-ms durations; `404`s buried inside transport-ok
  responses.
- **Trap → truth:** `5151` across many PFM journeys plus 404-inside-success → origin is the **shared
  THINK360 credential/token** whose renewal fails; everything holding the token dies at once.
- **Show:** a service evidence doc — `trns_sts: 0` (ok) wrapping `{"status_code": 404, "success":
  false}`. Layered-status decoding, trap #1.
- **Say:** "Simultaneity across unrelated journeys is the fingerprint of a shared credential."

### 6. `unipay-bbps-brownout` — no status field ever turns red
- **Timing:** the ratio climbs over ~3 minutes — **fire it early**, narrate while it builds, or fire
  it before a talky section. The incident lands only once the burst crosses the significance gate.
- **Watch:** billpay/autopay business-failure *ratio* climbing in `service_metrics`; every
  `trns_sts` stays `'success'`; payloads carry `responseReason: "Failure"` / `complianceReason:
  BFR003`.
- **Trap → truth:** nothing is red anywhere → origin is a **UNIPAY BBPS business-layer brownout**,
  visible only by decoding the response payloads and trending the ratio.
- **Show:** the watcher caught this with **zero** `audit_error` documents — the third watch arm reads
  business failures out of transport-ok payloads. Then the time-series trend in *Agent queries*.
- **Say:** "An agent that trusts status fields never fires here. Ours decodes the payload — transport
  and business status are different claims."

### 7. `gsa-validation-hang` — latency wearing a validation costume
- **Watch:** `gi_gsa_purchase_validate_checks` p95 blows out toward 15s (web channel `1001`);
  `TEY2GSA02` technical exceptions appear *after* the timeout.
- **Trap → truth:** `TEY2GSA02 "request validation"` reads like a validation-code bug → origin is the
  **external insurer dependency's latency**; the exception is the timeout's echo.
- **Show:** in the evidence, the ~15s `audit_service` duration *precedes* the journey exception —
  ordering by `(strt_time, seq)` is what proves direction.
- **Say:** "The error text lies about the layer. The timeline doesn't."

### 8. `demand-loan-improper-response` — unwrap the nest
- **Watch:** lending demand-loan-closure failures; `BSDML050 "Your Demand Loan closure request has
  failed… visit branch"` in the firehose.
- **Trap → truth:** the public wrapper code → the **innermost nested code**: `err_dtls` unwraps
  `BSDML050 → BSDML024 "received improper response"` — the CBS loan-discharge dependency returned a
  malformed body. A technical contract violation behind a customer-apology wrapper.
- **Show:** click the error evidence chip — the raw `err_dtls` JSON with the nested chain; `correlate`
  decoded it to the innermost code.
- **Say:** "The customer saw an apology. The agent read two levels deeper and named the contract."

### 9. `poison-retry-loop` — incidence beats volume
- **Watch:** a loud, fast-repeating count of identical `5151` exceptions — looks systemic by volume.
- **Trap → truth:** high error count → **one user, one session, one malformed `biz_req_input` replayed
  in a loop**. The `verify` incidence check (`distinct usr_id == 1`) is the discriminator.
- **Show:** the `verify` inspector pipeline counting distinct users; then the RCA's **deliberately low
  confidence (~0.2)** with its stated unknowns.
- **Say:** "Volume said outage; incidence said one broken client. And the agent says how sure it is —
  honestly."

### 10. `eis-gateway-pool-exhaustion` — the widest blast radius
- **Watch:** *every* EIS-backed tile degrades at once — offers, PFM, profile, lending; mixed business
  codes across unrelated journeys.
- **Trap → truth:** many different journeys' business exceptions firing together → no single vendor is
  the origin; **breadth itself implicates the shared EIS gateway / connection pool**.
- **Show:** *Collections analyzed* + blast radius on the incident card (journeys · channels · users);
  confidence ~0.3 because the gateway is inferred from breadth, not from a single smoking document.
- **Say:** "When everything behind one host fails together, the host is the hypothesis. The agent
  reasons about blast-radius shape, not just error text."

---

## Track 4 — manual chat investigation (INVESTIGATE tab)

Six beats, typed live in the UI (the scripted twin is `make demo-chat`). Best on a quiet board for
beats 1 and 6.

1. **Honesty first (quiet board).** Type: *"Customers report billpay autopay is failing. Can you
   check?"* → the agent searches 30 minutes of audit logs and answers **"no matching failures"**,
   listing the journey families it monitors. Say: "No evidence, no RCA, no hallucination."
2. **Context.** Fire any scenario (`fire eis-martech-brownout`) and let the watcher build the incident
   autonomously (~20s).
3. **Plain-words match.** Type: *"Users say the offers section on the app dashboard is broken and
   personalized offers will not load."* — no error code given. Triage maps the complaint to the
   journey catalog, the evidence ladder finds the failing transactions, joins them to the existing
   incident, and replies **"This matches incident … (technical fault)"** with a clickable chip.
   Phrasings for other scenarios: *"customers can't log in"* → `login-failures`; *"UPI payments are
   failing for many users"* → `upi-payment-failures`; *"pending bills aren't loading in billpay"* →
   `unipay-bbps-brownout` (after it trips).
4. **Follow-up, same session.** Type: *"Who was affected and what should we do about it?"* → answered
   from the linked incident document (blast radius, mitigation tiers). Say: "The conversation lives in
   Atlas too — `chat_sessions`, 7-day TTL, same platform as the logs it discusses."
5. **Screenshot triage.** Drag any error screenshot (or screenshot the ambered Offers tile) into the
   chat with just *"a user sent this — what's going on?"* → the vision LLM reads journeys/codes out of
   the image and runs the same ladder; the image is stored in `chat_images` and served back into the
   thread.
6. **Chat-launched investigation.** On a quiet board (≥5 min after any scenario), type: *"A customer
   complains their pre-approved personal loan offer keeps getting rejected in the app."* Single-user
   business rejections are the noise floor the watcher deliberately ignores — but a human asked. The
   chat claims its own incident (same idempotent path as the watcher), the DAG lights up, and the RCA
   lands back in the conversation. Say: "A change stream and a human question are two doors into the
   same investigation."

## Break-glass / resilience
- **Networking dies at the venue:** `make replay` plays a recorded run from `data/replay/` with zero
  network (rehearse with it; treat it as plan B).
- **Kill any component mid-demo:** the watcher resumes from its persisted change-stream token (no dupes,
  no gaps), the UI reconnects SSE automatically, and novasim buffers writes through an Atlas blip.
- **A view errors:** the ErrorBoundary shows a fallback and keeps the nav — switch tabs and continue.
- **Clean slate between rehearsals:** `make reset` (memory empty, kb restored — the run-1-vs-run-2
  contrast depends on this).

## One-command cheat sheet
```
make up             # agent + UI
make sim            # interactive simulator (status | scenarios | fire <id> | quit)
make reset          # clean board + reseed kb
make demo           # up + open the ops board
make demo-live      # guided 5-min core (scripts/demo.sh; --auto to rehearse)
make demo-chat      # guided chat track (scripts/demo_chat.sh; --auto to rehearse)
make replay         # offline fallback
make down           # stop agent + UI
make atlas-provision# verify collections + indexes (idempotent)
```
