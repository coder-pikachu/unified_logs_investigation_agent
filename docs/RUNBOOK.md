# RUNBOOK.md — Manual demo run + speaking notes

Drive the NOVA 2.0 RCA demo **by hand**, terminal by terminal, without the guided
`make demo-live` / `make demo-chat` scripts. Every step lists the `make` shortcut, the
raw command it runs underneath (use either), and the line to say. Atlas is cloud and
pre-provisioned — you only bring up the local agent + UI and drive the Java simulator.

Layout: 3 terminals side by side.
- **T1** — control (reset / up / down / grep beats)
- **T2** — simulator (stays focused during the demo; you type `fire <id>` here)
- **T3** — logs (optional: `tail -f .run/agent.log`)

---

## What this demo is (facilitator context — read first)

### The one-sentence thesis
**A single MongoDB Atlas database can serve *every* workload an autonomous root-cause-analysis
(RCA) agent needs — operational store, event bus, time-series metrics, lexical search, vector
search with automated embedding, hybrid retrieval, and durable agent memory — with zero bolt-ons.**
No Kafka, no Redis, no Elasticsearch, no external vector DB, no embedding service. That "one
platform" claim is the whole point; keep one datastore on screen the entire time.

### The story world
**NOVA 2.0** is a fictional banking super-app. A **Java CLI simulator (`novasim`)** plays its
"journey mesh" — ~40 concurrent user sessions across ~15 journeys (login, offers, UPI, PFM,
lending, billpay…) and their downstream calls to four shared backends: **EIS** (enterprise
gateway), **UNIPAY** (payments/BBPS), **Martech** (personalization), and **THINK360** (financial
fitness). It writes **real-shaped audit logs** to Atlas via a custom Log4j2 Mongo appender — the
same messy shapes as the real workbook (`Sample Log Data.xlsx`): spelling drift, `'NULL'` literals,
double-encoded JSON payloads, mixed int/string status codes. Nothing is faked or hardcoded.

### The simulator (`novasim`) — what the logs actually are
`novasim` is a Java 21 CLI that continuously **plays the NOVA 2.0 app the way real users would**,
at ~5 journey-actions/second across a pool of ~40 sessions. It is a *traffic generator*, not a
mock: every action mints a fresh `trns_id`, walks a real journey → downstream route path, and emits
documents in the exact contract shapes via a custom **Log4j2 Mongo appender**. When you "fire" a
scenario you are injecting *effects* (extra latency, an error rate, a business-failure ratio) into
that live traffic — the failures are woven into genuine background noise, not printed from a script.
**No scenario name is ever written to the data**; the agent only ever sees the resulting logs.

**Each user action produces up to four writes**, all sharing one `trns_id`:
- **`audit_transaction`** — the journey action itself (the thing the *user* did: "fetch offers",
  "send UPI", "log in"). Carries `cmnd_id` (the journey), `channel`, `trns_stts` success/error, and
  the business request/response payloads.
- **`audit_service`** — one per **downstream call** that action made to a shared backend (the thing
  a *backend* did). Carries `srvc_id` (the route), `systm_nm` (EIS/UNIPAY), transport status
  `trns_sts`, and the raw request/response envelopes. **This is where origins usually hide.**
- **`audit_error`** — written only when something fails; carries the customer-facing `err_cd`
  (business `BS*`, technical `TE*`, or legacy numeric like `5151`) and a possibly-**nested**
  `err_dtls` chain (the real code can be two levels deep).
- **`service_metrics`** — one time-series point per call (`durationMs`, `transportOk`,
  `businessOk`, keyed by route) that feeds the ops-board sparklines and the agent's p95 baseline.

**The systems in the mesh** (all reached *through* EIS — the enterprise gateway — except UNIPAY):
| System | What it is | Example routes (`srvc_id`) | Journeys that depend on it |
|---|---|---|---|
| **EIS** | The enterprise integration **gateway** every backend sits behind. Shared → a single-route failure fans out across unrelated journeys. | `eis_iam_authenticate`, `eis_marTech_getInteractOffers`, `eis_financialfitness_accessToken`, `eis_etb_customerprofile_querycustprofile`, `eis_cc_branchportal_account_cifAssociatedAccount` | login, offers, PFM (kyc/consent/summary), profile, cards |
| **UNIPAY** | Payments platform — **UPI switch** and **BBPS** bill-pay/autopay. (Note the authentic leading space in `systm_nm: ' UNIPAY'`.) | `unipay_upi_payment_transfer`, `unipay_payment_billpay_autopay_pendingbills`, `…_favouritebillers`, `…_activebillshistory` | UPI send-money, billpay autopay/favourites |
| **Martech** | Hyper-personalization / offers engine, called via the shared EIS `thirdParty/wrapper/Martech` route. | (EIS route `eis_marTech_getInteractOffers`) | offers fetch |
| **THINK360** | Financial-fitness / PFM data provider, reached via EIS on a shared **access-token** route — so one expired credential breaks every PFM journey at once. | (EIS routes `eis_financialfitness_accessToken`, `_summary`) | PFM kyc / consent / summary |

**Journeys vs routes vs ops jobs.** A **journey** (`cmnd_id`, shaped `domain_module_feature_action`,
e.g. `martech_hyper-personalization_offers_fetch`) is what the user did; a **route** (`srvc_id`) is
the shared downstream endpoint it called. Many journeys share one route — that sharing is exactly
why the loud symptom and the quiet origin live in *different* collections. Two journeys are **ops
jobs** (`ops_martech_audience_refresh_execute`, `ops_eis_config_deploy_execute`): background
maintenance transactions that succeed silently — and in the `martech-cif-desync` scenario a
*successful* ops job is the root cause of the failures that follow it.

**Simulator commands** (typed at the `nova>` prompt in T2): `status` (throughput + open scenarios),
`scenarios` (list injectable ids), `fire <id>` (inject a scenario's effects into live traffic),
`quit`. Firing writes a command into the `agent_state` collection; the running simulator polls it —
which is why the Ops-board "fire" buttons and the CLI drive the exact same path.

### What the agent is (and is NOT)
This is **not a chatbot over logs. There is no chat box in the core demo.** The agent runs
**autonomously**: a **Change Stream** on the audit collections wakes a **LangGraph** agent the
instant failures land, and it publishes a structured incident on its own. The facilitator never
"asks" it anything in the core narrative — they inject a failure into the simulator and the
investigation happens by itself. (The optional INVESTIGATE tab, Track 7, adds a human-driven chat
door into the *same* graph — but that's a bonus, not the thesis.)

### The single most important idea to land: origin ≠ loudest error
Every scenario is designed so **the error that screams loudest is never the root cause.** Fifty
users see login failures — but one shared IAM route is the origin. A dashboard fills with business
errors — but a *successful* ops job upstream caused them. The agent's value is **cross-collection
correlation**: it joins three audit collections on `trns_id`/`sessn_tkn_id`, orders events by time,
decodes layered transport-vs-business status, and names an **ORIGIN that is distinct from the
symptoms**. A single-log search (grep) can never do this. When you narrate, always contrast the
**loud decoy** with the **quiet origin**.

### How it works, in one breath
`novasim` writes audit docs → **Change Streams** wake the agent → a **9-node LangGraph** runs
`intake → collect → correlate → recall → hypothesize → verify → rca → recommend → persist` →
it streams node-by-node progress over **SSE** to a **React ops console** → the console shows the
agent *think*, cites the exact audit `_id`s, and lists every MongoDB query it fired. On a second
occurrence the agent **remembers** (native Atlas memory + automated embedding) and short-circuits
to a faster, more confident answer.

### The six claims you are proving (know these cold)
| # | Claim | On-screen proof |
|---|---|---|
| 1 | **One platform, six workloads** | One datastore on the architecture view; each node wears the Atlas capability badge it just used |
| 2 | **Change Streams are the event backbone** | Fire in the CLI → the incident card appears and the agent starts, unprompted, in seconds |
| 3 | **Agent memory is native + Automated Embedding** | Fire twice: run #2 is faster, higher-confidence, cites run #1; `grep embed agent/` finds no embedding client |
| 4 | **Hybrid retrieval done right** | The `recall` inspector shows both arms (`$search` for exact codes, `$vectorSearch` for semantics) fused by `$rankFusion` |
| 5 | **Cross-collection correlation beats single-log analysis** | Every RCA names an origin that is *not* the service that screamed; the *Agent queries* panel lists every query fired |
| 6 | **The workflow is legible** | The DAG lights node by node; each node's input/output (and recall/verify pipelines) are inspectable |

### The technology under each badge
- **Operational store** — `audit_transaction`, `audit_error`, `audit_service` (one doc per API
  call / error / downstream call).
- **Event bus** — Atlas **Change Streams** on the audit collections (resume-safe, debounced,
  significance-gated). *Not* on time-series — Change Streams aren't supported there.
- **Time series** — `service_metrics` (`timeField: ts`) powers the ops-board sparklines and the
  agent's p95 baseline-vs-incident check.
- **Lexical search** — Atlas **Search** (`*_search` indexes) for exact tokens like `TEEIS009`.
- **Vector search + Automated Embedding** — `voyage-4-lite` via the `autoEmbed` index type; the
  app passes **raw text**, Atlas vectorizes at write and query time. **There is no embedding client
  anywhere in `/agent`** — `make check-no-embed` enforces it.
- **Hybrid retrieval** — `$rankFusion` fuses the lexical and vector arms in one aggregation.
- **Agent memory** — LangGraph `MongoDBSaver` (`checkpoints`) for short-term thread state and
  `MongoDBStore` (`store`) for cross-thread route playbooks — both are just Atlas collections.

### The 9-node agent graph (what each node is doing on screen)
`intake` open the incident (Change Streams) · `collect` widen the evidence window (Time Series
baseline) · `correlate` order events + decode layered status, **pick the origin** · `recall`
hybrid `$rankFusion` memory lookup · `hypothesize` LLM proposes 2–4 causes, each citing real
`_id`s · `verify` turns each hypothesis into a **real MongoDB aggregation** and scores it · `rca`
LLM writes the causal chain + honest confidence · `recommend` three action tiers · `persist` writes
the incident and distils memory (text only — Atlas embeds it). A warm `recall → confirm` path skips
the LLM when memory hits — that's why run #2 is measurably faster.

### The LLM's role (say this if asked "is the LLM making it up?")
**No.** The deterministic code nodes (`collect`, `correlate`, `verify`, `persist`) do the analysis
with real MongoDB queries; the LLM only **narrates and ranks**. Every hypothesis must cite real
document `_id`s or it's discarded, and confidence is honest — some scenarios land at ~0.2 on
purpose because the evidence is genuinely thin. No hardcoded answers; the agent never sees the
scenario names or the ground-truth oracle.

### Audience & framing
Architects and builders. The tension you're resolving: *"agentic AI usually means stitching together
six databases and an embedding service."* The payoff: *"here it's one Atlas cluster, and here's the
agent solving a real cross-system incident live."* Lead every beat with the business outcome (a real
RCA), then reveal the Atlas capability that made it possible.

### On-screen glossary (terms the audience will see)
- **Journey** — a user-facing flow (login, offers, UPI payment…). **Route** — a shared downstream
  endpoint many journeys call (this is usually where the origin lives).
- **`trns_id` / `sessn_tkn_id`** — the join keys across the three audit collections.
- **Transport status vs business status** — a call can be `trns_sts: success` at the transport layer
  while its *payload* says the business operation failed. Decoding **both** is how the agent catches
  the "nothing is red" scenarios.
- **Origin vs symptom (decoy)** — the earliest downstream failure vs the loud user-facing errors it
  caused. **Blast radius** — how many journeys/channels/users an incident touched.
- **Fault class** — **technical** (transformation, timeout, credential, pool, malformed response)
  vs **business** (rule / data / compliance). A downstream *technical* failure stays technical even
  when the user sees a business code.

> **Deeper references:** `README.md` (full architecture + claim→proof), `docs/ARCHITECTURE.md`,
> `docs/SCHEMA.md` (data model), `docs/scenarios-ground-truth.md` (the oracle — the agent never
> reads it), `docs/DEMO.md` (the scripted four-track version of everything below).

---

## 0. Preflight (once, before the audience)

```bash
# .env present at repo root with MONGODB_URI, GROVE_*, ATLAS_* (copy .env.example)
test -f .env && echo ".env ok" || cp .env.example .env   # then fill it in

# Java 21 + Maven on PATH for the simulator
export JAVA_HOME=/opt/homebrew/opt/openjdk@21
java -version && mvn -version

# Atlas collections + search/vector indexes (idempotent re-verify)
make atlas-provision          # → python atlas/indexes.py
```
Optional dry-run offline check: `make replay` serves a recorded run with networking
disabled — your venue break-glass. Rehearse against it at least once.

---

## 1. Clean slate

```bash
make reset                    # → .venv/bin/python data/reset.py
```
Clears incidents / incident_memory / store / checkpoints / audit collections and
reseeds `kb_docs`. **Run this before every rehearsal** — a stale incident or a warm
playbook ruins the "first time we've seen this" beat.

---

## 2. Bring the stack up (T1)

`make up` runs three things; to do it fully by hand:

```bash
# a) venv + agent deps (skips if already installed)
make venv

# b) build the simulator jar (first run only; ~30s)
JAVA_HOME=/opt/homebrew/opt/openjdk@21 mvn -q -DskipTests -f novasim/pom.xml package

# c) agent: FastAPI + change-stream watcher on :8000
( cd agent && ../.venv/bin/python -m nova_agent ) > .run/agent.log 2>&1 &
#   wait for health:
until curl -sf localhost:8000/api/health >/dev/null; do sleep 0.5; done; echo "agent healthy"

# d) UI: Vite dev server on :5173
( cd ui && npm install --silent && npm run dev ) > .run/ui.log 2>&1 &
```
Or just: `make up`.

Open **http://localhost:5173**. Header MUST read `SSE stream live · MONGO up · GROVE up`.
Background traffic ticks the journey tiles; latency sparklines flow from the
`service_metrics` time-series collection. If the header is red, check `.run/agent.log`.

---

## 3. Start the simulator (T2 — keep focused)

```bash
make sim                      # → java -jar novasim/target/novasim.jar --rate 5
```
Interactive prompt. Commands: `status` · `scenarios` · `fire <id>` · `quit`.
Leave this terminal focused — you'll type `fire <id>` here on cue.

---

## 4. The 5-minute core (fire → autonomous incident → memory)

**Beat 0 — set the frame (say):**
> "Everything on this screen is one MongoDB Atlas database. No Kafka, no Redis, no
> Elasticsearch, no external vector DB, no embedding service. Watch."

**Beat 1 — fire the cascade (T2):**
```
nova> fire eis-martech-brownout
```
(Or click *EIS·MarTech brownout* on the Ops board — same `agent_state` command path.)

**Beat 2 — the board reacts (~seconds).** Offers tile ambers; MARTECH/EIS tiles climb;
`eis_marTech_getInteractOffers` latency ramps ~300ms → ~10s; `TEEIS009 Response
Transformation failed` errors surface across sessions.
> "That incident card just appeared on its own. That's a **Change Stream** waking the
> agent — not a poller. Nobody clicked anything."

**Beat 3 — watch it think (Agent Workflow tab).** DAG lights node by node:
`intake → collect → correlate → recall → hypothesize → verify → rca → recommend → persist`.
Each node wears its capability badge (Change Streams, Time Series, layered-status decode,
`$rankFusion`, Automated Embedding).
> "`recall` reports **no similar prior incidents — hybrid search returned 0 above
> threshold**. First time we've seen this."

**Beat 4 — the RCA lands (Incident Detail, ~15–25s in).** Swimlanes show the
cross-collection join; the **ORIGIN** marker sits on the shared EIS route, distinct from
the loud `BS000001` journey symptoms. Money line:
> "The user-facing offer failures across N sessions are **symptoms**. The origin is the
> shared EIS `thirdParty/wrapper/Martech` route, whose response transformation began
> failing — and here are the exact audit documents, clickable."

Click an evidence chip → raw-logs panel jumps to that `_id`. Recommendations: immediate
(circuit-break the offers widget), fix (EIS transformation config), prevention (latency +
`TEEIS009`-rate alert).

**Beat 5 — memory (fire again, T2):**
```
nova> fire eis-martech-brownout
```
> "Second time, the agent remembers." Run #2 **recall hits**: DAG short-circuits
> `recall → confirm → persist` (skips LLM hypothesize/verify), RCA confirmed faster with
> higher confidence, citing run #1; Memory tab shows playbook **hit count = 2**. That
> memory is native Atlas — no external memory service.

> **Timing trap:** to get a *distinct* run #2 (not a merge), re-fire **≥2 minutes** after
> the first. Inside the 120s collect window a re-fire merges into the open cascade.

---

## 5. Architect deep-dive beats (optional, T1 + Atlas UI)

**No embedding client (scripted grep):**
```bash
grep -rin "embed" agent/        # → no embedding client anywhere
grep -rin "autoEmbed" atlas/    # → the word lives only in index-definition JSON
```
> "The app never calls an embedding API. Atlas embeds `summary_text` and `body` at write
> and query time — **Automated Embedding**, `voyage-4-lite`, inside the database."

**The autoEmbed index def:** open `atlas/index_defs/incident_memory_vector.json` and
`kb_docs_vector.json` — `{"type":"autoEmbed","path":"summary_text","model":"voyage-4-lite"}`.
Show the same index in the Atlas UI.

**Hybrid `$rankFusion` (Agent Workflow → click `recall`):** the inspector prints the
literal aggregation — one `$rankFusion` per collection fusing a `$vectorSearch` arm with
`query:{text:…}` (no `queryVector`) and a `$search` lexical arm on exact `err_cd`/`srvc_id`.
> "Error codes like `TEEIS009` are exact tokens — lexical. 'Downstream transformation
> failures during offer fetch' is semantic — vector. `$rankFusion` combines them."

**A verify node's real pipeline (click `verify`):** the actual aggregation the agent ran
— incidence check (distinct `usr_id` on the route in the window) + ops/config precursor
scan. Deterministic MongoDB, not a prompt trick.

**LangGraph memory in Atlas (mongosh / Compass):**
```
use nova_rca
db.checkpoints.find().sort({_id:-1}).limit(1)   // MongoDBSaver — short-term thread state
db.store.find({}, {value:1})                     // MongoDBStore — cross-thread playbooks
db.getCollectionInfos({name:"service_metrics"})  // timeField ts, metaField meta
```
> "The checkpointer and the long-term store are both Atlas collections. And Change Streams
> don't run on time-series — that's why triggers sit on the audit collections."

---

## 6. Other scenarios (manual playbook)

Same rhythm — **fire (T2) → narrate board → incident appears itself → Incident Detail →
optional re-fire for memory.** One-liners; full per-scenario notes in `docs/DEMO.md` Track 3.

| `fire <id>` | Fault | The story in one line |
|---|---|---|
| `login-failures` | technical | 50 users can't log in; one shared IAM route is the cause |
| `upi-payment-failures` | technical | Every failed payment traces to one UNIPAY switch route (`U68`) |
| `eis-martech-brownout` | technical | Shared EIS Martech route degrades (`TEEIS009`, ~10s) — **flagship** |
| `martech-cif-desync` | business | A *successful* ops job caused the failures (no error logged) |
| `think360-token-expiry` | technical | One expired credential fans out across all PFM journeys |
| `unipay-bbps-brownout` | business | Business brownout with **no red status field anywhere** (fire early, ~180s) |
| `gsa-validation-hang` | technical | Dependency latency, not the validation code |
| `demand-loan-improper-response` | technical | Innermost nested code is the real cause (`BSDML050 → BSDML024`) |
| `poison-retry-loop` | technical | Loud count, one user — incidence beats volume (confidence ~0.2) |
| `eis-gateway-pool-exhaustion` | technical | Everything EIS fails at once — blame the shared gateway (confidence ~0.3) |

> Confidence is honest, not cosmetic: ~0.8 on clean single-route stories, ~0.45–0.65 on
> layered/desync stories, deliberately ~0.2–0.3 where evidence is genuinely thin. Narrate
> low confidence as a feature.

---

## 7. Chat investigation (INVESTIGATE tab, optional)

Type live in the UI. Best on a quiet board for beats 1 and 6. Scripted twin: `make demo-chat`.

1. **Honesty (quiet board):** *"Customers report billpay autopay is failing. Can you check?"*
   → "no matching failures" + the families it monitors. > "No evidence, no RCA, no hallucination."
2. **Context:** `fire eis-martech-brownout`, let the watcher build the incident (~20s).
3. **Plain-words match:** *"Users say the offers section is broken and personalized offers
   won't load."* → triage maps to the journey, evidence ladder finds the transactions,
   joins the existing incident, replies "This matches incident … (technical fault)".
4. **Follow-up (same session):** *"Who was affected and what should we do about it?"* →
   answered from the linked incident. > "The conversation lives in Atlas too — `chat_sessions`, 7-day TTL."
5. **Screenshot triage:** drag an error screenshot + *"a user sent this — what's going on?"*
   → vision LLM reads journeys/codes out of the image, runs the same ladder.
6. **Chat-launched RCA (quiet board, ≥5 min after any scenario):** *"A customer complains
   their pre-approved personal loan offer keeps getting rejected."* → single-user business
   rejections are the noise floor the watcher ignores, but a human asked; the chat claims
   its own incident and the DAG lights up. > "A change stream and a human question are two
   doors into the same investigation."

---

## 8. Teardown / reset between runs

```bash
make down                     # stop agent + UI (by port + pid)
make reset                    # clean board before the next rehearsal
```
`quit` in the simulator (T2) to stop it.

---

## Troubleshooting

- **Header red / `MONGO down`:** `tail -f .run/agent.log`; verify `MONGODB_URI` in `.env`
  and that your IP is on the Atlas access list.
- **`GROVE down`:** check `GROVE_BASE_URL` / `GROVE_API_KEY`; LLM nodes will stall without it.
- **No incident after firing:** confirm the simulator wrote (`status` in T2) and the watcher
  is alive in `.run/agent.log`; a stale board? `make reset` and re-fire.
- **Run #2 didn't short-circuit:** you re-fired inside the 120s window — it merged. Wait ≥2 min.
- **Port already in use:** `make down` (frees :8000 and :5173 by port), then `make up`.
- **Total network failure at the venue:** `make replay` — recorded run, zero network.
