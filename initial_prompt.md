**Role:** You are the tech lead and builder for a demo that must survive a live audience of **tech architects and builders**. Plan first, then build in phases. Every phase ends in something runnable, not a stub.

**Deliverable:** A working end-to-end system — Java CLI log generator → **MongoDB Atlas (cloud)** → LangGraph agent → live UI — startable with `make up` and demoable in under 5 minutes, with a 15-minute architect deep-dive path on top.

---

## 0. How to work

1. **Do not write code yet.** First produce `PLAN.md`: your reading of this brief, the architecture you're committing to, the phase plan with acceptance tests, and results of the two P0 spikes (§10 traps #2 and #3). Stop and confirm.
2. Build **phase by phase** (§9). Do not start phase N+1 until phase N's acceptance test passes and you've shown the output.
3. Keep a running `DECISIONS.md` — every non-obvious choice, one line each, with the reason. Version pins go here.
4. When this brief conflicts with reality (an API changed, a preview feature behaves differently), **say so and propose the fix**. Do not silently substitute or paper over it with a mock.

---

## 1. What we are actually selling

This demo proves **MongoDB Atlas is the unified data platform for agentic AI** — one database serving every workload an agent needs, orchestrated by LangGraph. The log-RCA use case is the vehicle. Grade every decision against these six claims; cut anything that doesn't advance one.

| # | Claim | How it's proven on screen |
|---|---|---|
| 1 | **One platform, six workloads.** Operational document store, Change Streams event bus, **time series** metrics, **Atlas Search** full-text, **Vector Search with Automated Embedding**, and durable agent memory — all Atlas, zero bolt-ons. | Architecture slide has exactly one datastore. Each capability is *named on screen at the moment it fires* (a small badge on the workflow node: "$rankFusion — Atlas Search + Vector Search"). |
| 2 | **Change Streams as the event backbone.** The agent isn't polled or cron'd; it wakes because the data changed. | Error fired in the CLI → within seconds the UI shows the agent starting, unprompted. |
| 3 | **Agent memory is native.** LangGraph checkpointer + long-term store live in Atlas; past incidents are recalled by vector search — and the app **never calls an embedding API**: Automated Embedding (Voyage `voyage-4-lite`) embeds and syncs inside the database. | Fire the same scenario twice. Second run is faster, higher-confidence, cites the first incident. Then show the codebase: `grep -r embed` finds no embedding client anywhere. That grep is a scripted demo beat. |
| 4 | **Retrieval done right: hybrid.** Error codes like `TEEIS009` or `BSDML050` are exact tokens — lexical `$search` territory. "Downstream transformation failures during offer fetch" is semantic — `$vectorSearch` territory. `$rankFusion` combines them. | The recall node's inspector shows both arms of the hybrid query and the fused ranking. Architects will lean in here. |
| 5 | **Correlation across collections beats single-log analysis.** Three audit collections (transaction / error / service) joined on `trns_id` and `sessn_tkn_id`; the loudest error is never the origin. | Every scenario's RCA names an origin that is *not* the service that screamed. Timeline swimlanes make the join visible. |
| 6 | **The workflow is legible.** The audience watches the agent think, not a spinner. | LangGraph DAG lights up node by node; every node's input, output, and (for verify) the *actual aggregation pipeline it ran* are inspectable. |

**Explicit anti-goal:** this is not a chatbot over logs. No chat box. The agent runs autonomously and publishes a report.

**The 90-second core narrative** (build backwards from this):

> Screen shows a live YONO 2.0 ops board — journeys ticking over (dashboard, billpay, PFM, lending, offers), downstream-system tiles (EIS, UNIPAY, Martech, THINK360) green, latency sparklines flowing from the time series collection. Presenter switches to the Java CLI, types `fire eis-martech-brownout`, hits enter. Within seconds the Martech tile ambers: `eis_marTech_getInteractOffers` latency sparkline climbs from ~300ms toward 10s, `TEEIS009 Response Transformation failed` counts tick up, and `martech_hyper-personalization_offers_fetch` errors surface across multiple user sessions. An incident card appears by itself — Change Streams, nobody clicked anything — and the view switches to the agent workflow. Nodes light: *intake → collect → correlate → recall → hypothesize → verify → rca → recommend → persist*. `recall` reports "no similar prior incidents; hybrid search returned 0 above threshold." `verify` shows the aggregation it ran to test the leading hypothesis. Twenty-five seconds in, the RCA lands: the user-facing offer failures across N sessions are symptoms; the origin is the shared EIS `thirdParty/wrapper/Martech` route, whose response transformation began failing at 16:14:08 — with the causal chain and the exact audit documents cited, clickable. Recommendations: immediate mitigation (circuit-break the offers widget, dashboard degrades gracefully), the fix (EIS transformation config for the Martech response contract), prevention (latency + `TEEIS009`-rate alert on the route). Presenter fires the same scenario again. `recall` hits — the previous incident and its playbook surface, the agent short-circuits to a confirmed RCA in a third of the time, and the memory panel shows the playbook's hit count at 2.

**Audience & pacing:** architects and builders. `DEMO.md` gets two tracks — the 5-minute core above, and a 15-minute deep dive: open the `autoEmbed` index definition in Atlas, inspect a verify node's pipeline, show LangGraph checkpoint documents in the `checkpoints` collection, run the `grep -r embed` beat, show the time series collection definition.

---

## 2. The data — read this before designing anything

`Sample_Log_Data.xlsx` (in `/data`) contains real-shaped sample logs from **YONO 2.0** (a large retail-banking super-app). Three sheets → **three MongoDB collections**. Row 1 is a title banner, row 2 blank, row 3 headers, data from row 4. This section summarizes what's in it; formalize it as `SCHEMA.md` in P1 with the seed loader.

### 2.1 The three collections

**`audit_transaction`** — one document per API call into the platform (sheet "audit transaction", banner "LOGS DATA FOR YONO 2.0 API CALLS"):

| Field | Meaning | Sample |
|---|---|---|
| `msg_id` | numeric message id | `61461979` |
| `trns_id` | **transaction id — the correlation key.** epoch-millis + random suffix | `1783420778003ix0AcsX0vwDd6c2bb` |
| `sessn_tkn_id` | session token id — groups many `trns_id`s into one user session | `17834207286105I79wonAkpwa9b29a` |
| `clnt_ip_addr` | client IP | `10.191.199.66` |
| `req_no` | request number — hex uuid **or** `yonoweb_237808889` style (format varies by channel) | |
| `usr_rltnshp_no` | customer relationship number | `85002719907` |
| `trns_stts` | `error` \| `success` (note spelling: double-t) | |
| `strt_time`, `end_time` | ms-precision timestamps with `+05:30` offset | `2026-07-07 16:09:38.022+05:30` |
| `usr_id` | 19-digit numeric id — **mangled to float by Excel** (`1.73070901334081e+18`); true value visible in payloads: `1730709013340810605` | |
| `usr_typ` | `ETB_CUSTOMER` | |
| `cmnd_id` | **the journey/feature identifier**, pattern `domain_module_feature_action` | `martech_hyper-personalization_offers_fetch`, `lending_demand_demand-loan-closure_manage`, `gi_gsa_purchase_validate_checks`, `pfm_financial-fitness_customer_kyc_fetch`, `home_dashboard_notification_getAllNotifications`, `loan_personal_papl_getEligibleLoanDetails`, `feedback_customer_txn-counter-and-rules_fetch`, `home_dashboard_cards_getAllCCAccountSummary`, `home_user_preferred_lang_set`, `pfm_financial-fitness_consent_fetch` |
| `chnl_id` | channel: `2001` (mobile), `1001` (web — the `yonoweb_` req_no row) | |
| `biz_req_input` | JSON **string** of business request | `{"refNo": "SBIY2...", "action": "Y"}` |
| `biz_resp_output` | JSON string — often **double-encoded** (JSON inside a JSON string): `{"response": "{\"totalMsgs\":0,...}"}` | |
| `crtd_by`, `crtd_on` | `TransAdtUser` + write timestamp | |
| `trace_id` | mostly literal string `'NULL'`; occasionally a hex trace id — **cannot be relied on**; `trns_id` is the join key | |
| `nfrchk` | `'NULL'` | |

**`audit_error`** — one document per error event (sheet "audit error ", note trailing space in sheet name):

| Field | Meaning | Sample |
|---|---|---|
| `msg_id`, `trns_id`, `sessn_tkn_id` | join keys as above | |
| `err_cd` | error code — mixed vocabularies: `BS000001` (generic business), `TEY2GSA02` (technical, journey-specific), `5151` (numeric legacy) | |
| `err_typ` | `BUSINESS_EXCEPTION` \| `TECHNICAL_EXCEPTION` | |
| `err_dscrptn` | human text (typos included: "Exception occur during Request vaidation…") | |
| `err_dtls` | JSON string keyed by **business error code**, possibly **nested**: `{"BSDML050":{"data":{"BSDML024":{"data":{"loan_discharge":"received improper response"},"message":"…technical issue…"}},"message":"Your Demand Loan closure request has failed…"}}` — the innermost code is the real cause | |
| `crtd_by`, `crtd_on`, `err_time` | `ErrorAdtUser` + timestamps | |
| `usr_id` | as above | |
| `biz_err_cd_1..5`, `biz_err_cd_1_msg..5_msg` | flattened business error codes + messages; unused slots are the string `'NULL'` | `BSYHP003` / "CIF Is Not Recognized By Martech." · `BSPAPL010` / "Sorry! This offer is not available to you." |

**`audit_service`** — one document per **downstream/surrounding-system call** (sheet "audit service"):

| Field | Meaning | Sample |
|---|---|---|
| `msg_id`, `trns_id`, `sessn_tkn_id`, `usr_id` | join keys | |
| `trns_sts` | **single-t spelling** — and mixed vocabulary: `success` \| `0` (ok) \| `-2` (failure) | |
| `err_cd` | mixed again: HTTP-ish `200`, internal `1`, technical `TEEIS009`, or empty | |
| `err_msg` | `No data found`, `Failure`, `Response Transformation failed.` | |
| `srvc_id` | downstream operation id | `eis_marTech_getInteractOffers`, `eis_financialfitness_accessToken`, `eis_financialfitness_summary`, `eis_etb_customerprofile_querycustprofile`, `eis_cc_branchportal_account_cifAssociatedAccount`, `unipay_payment_billpay_autopay_pendingbills`, `unipay_payment_billpay_autopay_query_favouritebillers`, `unipay_payment_billpay_autopay_get_active_activebillshistory` |
| `systm_nm` | downstream system — `' UNIPAY'` (**leading space in the data**), `'EIS'` | |
| `api_url` | full downstream URL | `https://eissiuat.sbi.co.in/gen6/gateway/misc/thirdParty/wrapper/Martech/services`, `https://10.176.57.27:4443/bbps-autopay-service/upcomingBills` |
| `rqst_id_sent`, `rqst_id_rcvd` | downstream request ids (`SBIY22…`, `SB41…`) | |
| `srvc_rqst`, `srvc_rspn` | JSON-string payloads — see layered semantics below | |
| `crtd_by`, `crtd_on`, `strt_time`, `end_time` | `ServiceAdtUser` + timings — **duration is `end_time − strt_time`, computable per call** | |

### 2.2 Correlation hierarchy — this is the agent's spine

```
sessn_tkn_id (user session)
  └── trns_id (one API call / journey action)        ← primary correlation key
        ├── audit_transaction  (1 doc: the call itself)
        ├── audit_error        (0..n docs: what went wrong)
        └── audit_service      (0..n docs: downstream calls made)
```

The `collect` node widens outward along a ladder: **trns → session → same `cmnd_id`/`srvc_id` across sessions in the time window → time-series baseline**. That ladder is what turns "one user hit an error" into "the Martech route is down for everyone."

### 2.3 Layered status semantics — the demo's best trap for naive analysis

The data proves status fields lie:

- `audit_service.trns_sts = 'success'` **while** the response payload carries `{"reason":{"responseCode":"001","responseReason":"Failure","complianceReason":"BFR003"}}` (UNIPAY) — transport succeeded, business failed.
- `trns_sts = 0` (ok) **while** `EIS_RESPONSE` contains `{"status_code": 404, "message": "Data Not Found", "success": false}` (THINK360 financial-fitness).
- Nested error codes: `BSDML050` publicly wraps `BSDML024 → "loan_discharge": "received improper response"` — the innermost code names the real dependency failure.

The `correlate` node must decode payloads (attempt JSON-parse up to 2 levels for double-encoding) and classify each event on **both** transport and business status. An agent that trusts status fields at face value will get the wrong RCA — and that contrast is worth narrating in the deep-dive track.

### 2.4 Stories already visible in 30 sample rows (ground your scenarios in these)

1. `eis_marTech_getInteractOffers` at **10.1s duration** with `TEEIS009 Response Transformation failed`, twice, ~2s apart, **different sessions/users** → systemic downstream degradation, and the matching journey-side failure is `martech_hyper-personalization_offers_fetch` → `BS000001/BSYHP003`.
2. `gi_gsa_purchase_validate_checks` at **15.1s** then `TEY2GSA02` technical exception → timeout-shaped validation failure (web channel, `chnl_id 1001`).
3. `lending_demand_demand-loan-closure_manage` at **11.7s** → nested `BSDML050(BSDML024: "received improper response")` → malformed response from the loan-discharge dependency.
4. `eis_financialfitness_accessToken` (THINK360 login, JWT with `expiry` field) alongside a fast-failing (5ms) `pfm_financial-fitness_customer_kyc_fetch` with legacy `err_cd 5151` → credential/token dependency chain.
5. UNIPAY autopay endpoints returning transport-success/business-failure with compliance codes → brownout that never trips a red status field.

### 2.5 Data quirks — seed-loader repair rules (P1)

The generator must reproduce the *authentic* messiness; the seed loader must repair only the *Excel-inflicted* damage:

| Quirk | Treatment |
|---|---|
| `usr_id` float-mangled (`1.73070901334081e+18`) | **Excel damage — repair.** Recover true value from payloads where present (`1730709013340810605`); else synthesize a consistent 19-digit id. Store as string. |
| Literal string `'NULL'` | **Excel/export artifact — repair** to absent field on seed. But the **generator keeps emitting `'NULL'` strings** in `biz_err_cd_*` slots and `trace_id` — that's the real system's behavior and the agent must cope. |
| `' UNIPAY'` leading space | Authentic — **preserve** in generated data; the agent normalizes on read. |
| `trns_stts` vs `trns_sts` spelling drift across collections | Authentic — **preserve**. Do not unify field names; the glossary handles it. |
| Double-encoded JSON in `biz_resp_output`/`srvc_rspn` | Authentic — **preserve and reproduce**; agent decodes up to 2 levels. |
| Mojibake `â€¢` (a `•` mask through the wrong codepage) | Excel damage — repair to `•`/`XXX` masking; generator uses clean masks (`XXX`, `XXXXXXXXXX` for PAN). |
| Timestamps `+05:30`, ms sometimes truncated (`16:15:20.59`) | Parse to BSON Date (UTC internally); display in IST. Generator emits full ms. |
| Timestamp triple: `strt_time`, `end_time`, `crtd_on` | `crtd_on` is the write time (can lag/reorder); ordering logic uses `strt_time`/`end_time` + a monotonic `seq` (§10 trap #5). |

**Sensitivity:** sample values include UAT hostnames (`eissiuat.sbi.co.in`), internal IPs, and CIF-like numbers. Treat as internal. The generator synthesizes lookalikes (`eis-uat.internal`, fresh 10.x IPs, fresh relationship numbers); never hardcode the real hosts anywhere that could be published.

---

## 3. Architecture

```
┌────────────────────────────────┐
│  Java CLI  "yonosim"           │  Log4j2, ThreadContext{trnsId, sessnTknId}
│  ├ auto traffic (journeys/sec) │  simulates YONO journeys + EIS/UNIPAY/
│  └ fire <scenario>             │  Martech/THINK360 downstream calls
└───────────────┬────────────────┘
                │ Log4j2 → Mongo appender (3 audit streams + metrics)
                ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │                    M O N G O D B   A T L A S  (cloud)               │
   │  audit_transaction · audit_error · audit_service                    │
   │  service_metrics (time series) · incidents · incident_memory        │
   │  kb_docs · checkpoints · checkpoint_writes · store · feedback       │
   │  · agent_state                                                      │
   │  Change Streams · Atlas Search · Vector Search (Automated           │
   │  Embedding, voyage-4-lite) · TTL · $rankFusion                      │
   └────────┬──────────────────────────────────────────────┬─────────────┘
   change stream on audit_error                    reads / writes
            │  (+ audit_service failures)                   │
            ▼                                               │
   ┌────────────────────────────────────────────────────────┴───────────┐
   │  Agent service (Python)                                            │
   │  ├ watcher: resume-token-safe, debounced, idempotent               │
   │  └ LangGraph: intake→collect→correlate→recall→hypothesize          │
   │               →verify⤴→rca→recommend→persist  (+ learn on feedback)│
   │     memory: MongoDBSaver (thread) + MongoDBStore (long-term)       │
   │     LLM: Grove API (OpenAI-compatible proxy) · gemini-flash-lite   │
   │     embeddings: none in code — Atlas Automated Embedding           │
   └───────────────────────┬────────────────────────────────────────────┘
                           │ FastAPI + SSE (node-level events)
                           ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │  UI — Live Ops board · Agent Workflow · Incident · Memory          │
   └────────────────────────────────────────────────────────────────────┘
```

**Stack** (pin exact versions in `DECISIONS.md`):

| Layer | Choice | Notes |
|---|---|---|
| Log generator | Java 21, Maven, picocli, Log4j2 | §10 trap #1 on the Mongo appender |
| Database | **MongoDB Atlas (cloud)** — dedicated project + cluster for the demo | Provision via Atlas CLI or Terraform script in `/atlas`; §10 trap #2 |
| Embeddings | **Atlas Vector Search Automated Embedding**, model **`voyage-4-lite`** (Voyage 4 family, 1024-dim default) | Index type `autoEmbed`; public preview — P0 spike verifies syntax/tier (§10 trap #3). **No embedding client in any codebase.** |
| LLM | **Grove API** — internal OpenAI-compatible proxy, model **`gemini-flash-lite`** | `ChatOpenAI(base_url=$GROVE_BASE_URL, api_key=$GROVE_API_KEY, model=$GROVE_MODEL)`; §5.3.4 |
| Agent | Python 3.12, LangGraph, `langgraph-checkpoint-mongodb`, PyMongo | |
| API | FastAPI + SSE | |
| UI | React + Vite + TypeScript + Tailwind | |

`docker-compose.yml` now contains only `yonosim` (optional — can also run via `make sim`), `agent`, and `ui`; Atlas is reached via `MONGODB_URI`.

---

## 4. Repo layout

```
/yonosim         Java CLI generator (Maven)
/agent           LangGraph agent + change stream watcher + FastAPI
  /graph         nodes.py, state.py, graph.py, prompts/ (incl. field glossary)
  /memory        checkpointer.py, store.py, recall.py
  /watcher       change_stream.py, debounce.py
  /api           routes.py, sse.py
/ui              React app
/atlas           provision script (Atlas CLI/Terraform), index definitions
                 (search + autoEmbed vector + TTL + compound), teardown
/data            Sample_Log_Data.xlsx, seed.py (repair rules §2.5), replay fixtures
/docs            PLAN.md, SCHEMA.md, DECISIONS.md, DEMO.md, ARCHITECTURE.md
docker-compose.yml
Makefile         make up / seed / sim / demo / replay / reset / atlas-provision
```

---

## 5. Component specs

### 5.1 Java CLI — `yonosim`

Simulates the YONO journey mesh **in one process**, emitting documents in the exact §2 shapes to the three audit collections plus `service_metrics`.

**Journey catalogue** (from `cmnd_id`s in the data, extend to ~15): home dashboard (notifications, CC summary, preferred-lang), PFM financial fitness (kyc, consent, summary — backed by THINK360 via EIS), martech offers (backed by Martech via EIS `thirdParty/wrapper` route), lending (PAPL eligibility, demand-loan closure — backed by CBS/loan systems via EIS), GI insurance (GSA purchase validation), billpay/autopay (backed by UNIPAY BBPS endpoints), customer profile (EIS CustEnquiry).

**Downstream model:** each journey triggers 0–4 `audit_service` calls against a small routing table of systems (`EIS`, `UNIPAY`, plus EIS destinations `MARTECH_DWH`, `IT_JVP`/THINK360, CBS) with realistic latency distributions (log-normal; EIS ~200–600ms p50), layered statuses per §2.3, and the authentic payload envelopes (`{"head":…,"reason":…}` for UNIPAY, `{"TXN_TYPE":…,"EIS_PAYLOAD":…}` / `{"ERROR_CODE":"","EIS_RESPONSE":…}` for EIS).

**Correlation:** each simulated user session gets a `sessn_tkn_id`; each journey action a fresh `trns_id` (epoch-millis + random suffix, matching the observed format), both pushed into Log4j2 `ThreadContext` and stamped on every emitted document. A monotonic per-`trns_id` `seq` is added (§10 trap #5).

**Background traffic:** default ~5 journey-actions/sec across a pool of ~40 sessions, mostly success, with the authentic noise floor: UNIPAY "No data found" 200s, business-failure-inside-success responses at a low rate, occasional benign `BSPAPL010`-style business exceptions, periodic ops/audit actions (config deploys, audience refreshes — emitted as *success* transactions, needed by scenario 2).

**Interactive commands:**

```
> status                          # sessions, actions/sec, docs written, Atlas conn
> scenarios                       # list injectable failures
> fire eis-martech-brownout       # inject one cascade
> fire martech-cif-desync --delay 45s
> fire <id> --burst 2             # repeat, for the memory demo
> rate 20                         # change background actions/sec
> quiet / loud                    # console mirroring on/off
> quit
```

**Non-negotiables:** emitted documents contain **no scenario names, no hints, no synthetic root-cause field** — the agent has to earn it from the same evidence a human SRE would have. Console mirroring is presenter-only, never written to Atlas. Writes go through the Log4j2 appender (§10 trap #1) wrapped in `AsyncAppender`; if Atlas is unreachable, buffer and retry — never crash mid-demo.

### 5.2 MongoDB Atlas

**Collections:**

| Collection | Purpose |
|---|---|
| `audit_transaction`, `audit_error`, `audit_service` | The three log streams, shapes per §2. TTL 7d on write-time. **`audit_error` is the change-stream trigger source.** |
| `service_metrics` | **Time series collection** — `timeField: ts`, `metaField: {service, system, kind}`, granularity `seconds`. One measurement per journey action and per downstream call: `{ts, meta, durationMs, transportOk, businessOk}`. Powers ops-board sparklines and the agent's baseline/trend checks. Written by `yonosim`. |
| `incidents` | One doc per analyzed `trns_id`/incident group. The dashboard reads this. |
| `incident_memory` | Distilled learnings. Text field `summary_text` (signature + narrative + resolution) — **vector-indexed via Automated Embedding**; no embedding field is ever written by code. |
| `kb_docs` | ~15 curated runbook/ownership/known-issue entries in YONO vocabulary (who owns EIS routes, UNIPAY compliance codes incl. `BFR003`, THINK360 token lifecycle, `err_cd` glossary). Same `autoEmbed` treatment on `body`. |
| `checkpoints`, `checkpoint_writes` | LangGraph `MongoDBSaver` — thread/short-term memory. |
| `store` | LangGraph `MongoDBStore` — cross-thread memory: per-route/per-journey playbooks, hit counts, fixes that worked. |
| `feedback` | 👍/👎 + corrections from the UI; feeds the learn path. |
| `agent_state` | Change-stream resume tokens, watcher heartbeat. |

**Indexes:** `{trns_id:1}`, `{sessn_tkn_id:1, strt_time:1}`, `{cmnd_id:1, strt_time:-1}` on transactions; `{trns_id:1}`, `{err_cd:1, err_time:-1}` on errors; `{trns_id:1}`, `{srvc_id:1, strt_time:-1}`, `{systm_nm:1, strt_time:-1}` on service; TTLs; unique `{trns_id:1}` on `incidents`.

**Search indexes (create in P0 — they take minutes to build, never mid-demo):**
- **Atlas Search (lexical)** over `audit_error` (`err_cd`, `err_dscrptn`, `err_dtls`, `biz_err_cd_*_msg`) and `audit_service` (`err_cd`, `err_msg`, `srvc_id`) — powers the UI log-search box and the lexical arm of recall. Keyword analyzer on code fields so `TEEIS009` matches exactly.
- **Vector Search `autoEmbed`** on `incident_memory.summary_text` and `kb_docs.body`, model `voyage-4-lite`. Queries pass **raw text**; Atlas embeds at write and query time. Exact index/query JSON: verify against current docs in the P0 spike (public preview; syntax may drift) and record in `DECISIONS.md`.

**Change stream trigger:**
- Watch `audit_error` inserts (every doc there *is* an error — no `$match` gymnastics needed), plus a second watch on `audit_service` matching failure statuses (`trns_sts: '-2'` or technical `err_cd`s) to catch downstream-only degradation before it surfaces as user errors.
- **Debounce:** first error for a `trns_id` opens a collection window (default 4s, configurable). If ≥3 distinct `trns_id`s error inside one window sharing a signature (`err_cd` or `srvc_id`), escalate the incident grouping to the shared dimension (the route, not the user). Only after the window closes does the graph run.
- **Idempotent:** unique index upsert on the incident key. A restart mid-cascade must not duplicate.
- **Resume-token safe:** persist tokens in `agent_state` after each processed batch. Kill the agent, restart, no gaps and no replays. *This is an acceptance test.*
- Note: change streams are **not supported on time series collections** — the trigger stays on the audit collections; `service_metrics` is read-side analytics only. (Verify current server behavior; record in `DECISIONS.md`.)

### 5.3 LangGraph agent

#### 5.3.1 State

```python
class AgentState(TypedDict):
    incident_key: str                # trns_id, or escalated group key (route/signature)
    trns_ids: list[str]
    sessn_tkn_ids: list[str]
    trigger: dict                    # the change stream event(s)
    txn_docs: list[dict]             # audit_transaction
    err_docs: list[dict]             # audit_error
    svc_docs: list[dict]             # audit_service
    context_docs: list[dict]         # widened: same session / same cmnd_id / same srvc_id, ±120s
    metrics_baseline: dict           # from service_metrics: p50/p95/err-rate, window vs 30-min baseline
    timeline: list[TimelineEvent]    # ordered, cross-collection, layered-status-decoded, deltas
    journeys_involved: list[str]     # cmnd_ids
    systems_involved: list[str]      # systm_nm / srvc_id
    origin_candidate: dict | None    # deterministic first-anomaly guess
    recalled_incidents: list[dict]   # hybrid $rankFusion results
    recalled_kb: list[dict]
    playbook: dict | None            # from MongoDBStore
    hypotheses: list[Hypothesis]     # each cites doc _ids
    verifications: list[dict]        # pipeline + result per hypothesis
    rca: RCAReport | None
    recommendations: list[Recommendation]
    confidence: float
    iteration: int                   # guards verify→collect loop
    node_trace: list[NodeTrace]      # name, started, ended, ms, summary — drives the UI
    token_usage: dict
    errors: list[str]
```

#### 5.3.2 Nodes

| Node | Kind | Does |
|---|---|---|
| `intake` | code | Normalize trigger(s), set `thread_id = incident_key`, open the incident doc as `status: analyzing` so the UI renders it immediately. |
| `collect` | code | The §2.2 widening ladder: all three collections by `trns_id`(s) → session context → same `cmnd_id`/`srvc_id` across sessions ±120s → `service_metrics` baseline (current window vs preceding 30 min, per route). Brief wait for stragglers. Bounded (§10 trap #9). |
| `correlate` | code | Build the cross-collection causal timeline: sort by `(strt_time, seq)`, attribute to journey/system swimlanes, **decode layered statuses** (§2.3 — parse payloads up to 2 levels, classify transport vs business), unwrap nested `err_dtls` chains to the innermost code, compute inter-event deltas and incidence (how many sessions/users share the signature), read the metrics trend. Emit `origin_candidate` = first anomalous event, explicitly distinguished from the loudest. **Pure Python, no LLM.** This node is why the demo is credible. |
| `recall` | code | **Hybrid retrieval, one aggregation:** `$rankFusion` combining (a) `$vectorSearch` over `incident_memory.summary_text` + `kb_docs.body` with the raw incident narrative as the text query — Automated Embedding does the rest — and (b) `$search` lexical arm keyed on exact tokens (`err_cd`s, `srvc_id`, `biz_err_cd`s). Also read the route/journey playbook from `MongoDBStore`. Emit both arms + fused ranking to the UI (claim #4's proof), including the empty result on run #1. |
| `hypothesize` | LLM | 2–4 candidate root causes from the timeline + recall context. **Each must cite specific document `_id`s; uncited hypotheses are discarded in code.** Prompted with the field glossary (§10 trap #10). |
| `verify` | code | Turn each hypothesis into a MongoDB aggregation and run it: incidence checks ("distinct `usr_id`s with `TEEIS009` on this route in the window — 1 or many?"), baseline comparisons against `service_metrics` ("p95 for `eis_marTech_getInteractOffers` this window vs baseline"), precursor checks ("any ops/config transaction on the implicated component in the prior 10 min?"). Score hypotheses on evidence. Conditional edge: all fail and `iteration < 2` → back to `collect` with a widened window; else proceed with best-scored. **Persist the literal pipeline + result into `verifications` — the UI shows them.** |
| `rca` | LLM | Final report: root cause, ordered causal chain with timings, contributing factors, blast radius (journeys, channels, user count), evidence citations, confidence 0–1, and explicit `unknowns` — state what couldn't be determined rather than fabricate. |
| `recommend` | LLM | Three tiers: **immediate mitigation** (e.g., circuit-break the widget), **fix** (concrete — the route/config/contract implicated), **prevention** (the alert or test that should have caught it — often a `service_metrics` threshold). Each with owning system and effort/impact. |
| `persist` | code | Write the incident doc; write a distilled `summary_text` memory to `incident_memory` (**text only — Atlas embeds it**); upsert the playbook in `MongoDBStore` (seen count, last seen, confirmed fixes). |

Plus a `learn` path on `feedback` writes: a 👎 with correction lowers the memory's confidence and amends the playbook so the next identical incident answers differently. Ship the plumbing in P6; demo it in the deep-dive track if time allows.

#### 5.3.3 Streaming

`stream_mode=["updates", "custom"]`. Every node start/finish plus meaningful intra-node progress ("collected 1,214 docs across 3 collections", "hybrid recall: 2 hits, top score 0.91") over SSE. **The UI must never show an unexplained gap longer than ~2s.**

#### 5.3.4 Models

- **LLM (all reasoning roles):** Grove API — OpenAI-compatible; `ChatOpenAI(base_url=$GROVE_BASE_URL, api_key=$GROVE_API_KEY, model=$GROVE_MODEL)` with `GROVE_MODEL=gemini-flash-lite`, temperature 0. Keep the fast/reasoning **role abstraction** (`LLM_FAST_MODEL`, `LLM_REASONING_MODEL`, both defaulting to `gemini-flash-lite`) so a heavier model can be dropped into the reasoning role by env var alone.
- `gemini-flash-lite` is a *light* model — design for it: the deterministic nodes (`correlate`, `verify`) carry the analytical weight; LLM prompts are tight, schema-constrained (structured outputs if the proxy supports them — P0 spike; else strict JSON-mode + pydantic validation + one retry-with-error-feedback), and include the field glossary. This division of labor is itself a talking point for the architect audience: *the database and deterministic code establish the facts; the LLM narrates and ranks.*
- **Embeddings: none in code.** Automated Embedding (`voyage-4-lite`) at the index. The `grep -r embed` demo beat depends on keeping it that way.
- Log token usage per node; show the running counter in the UI.

### 5.4 API

`GET /api/incidents` · `GET /api/incidents/{key}` · `GET /api/logs?trnsId=|sessnTknId=` · `GET /api/search?q=` (**Atlas Search over the audit collections — claim #1's full-text proof in the UI**) · `GET /api/metrics?service=&window=` (time series for sparklines) · `GET /api/stream` (SSE: agent node events + new incidents) · `POST /api/feedback` · `GET /api/memory` · `POST /api/scenarios/{id}/fire` (optional) · `GET /api/health`.

### 5.5 UI

Four views, built in this order.

**1. Live Ops board.** Journey tiles (dashboard, billpay, PFM, lending, offers, insurance) and downstream-system tiles (EIS, UNIPAY, Martech, THINK360) with latency/error-rate sparklines fed by `service_metrics`; a throttled log firehose color-coded by level/status (business-failure-inside-success gets its own tint — the layered-status story made visible); incident cards appearing in real time; a **search box backed by `$search`** over the audit collections. The "before" state that makes the failure land.

**2. Agent Workflow.** *The money shot.* The LangGraph DAG, nodes lighting pending/running/done/skipped with elapsed ms; the verify→collect back-edge drawn and animated when it fires. Click any node: input, output, and — for `recall` and `verify` — the **actual aggregation pipeline** (`$rankFusion` stages, incidence checks) pretty-printed. Capability badges per claim #1. Running token/cost counter.

**3. Incident detail.** Timeline swimlanes by journey and downstream system across all three collections, origin flagged distinctly from symptoms; RCA narrative with inline evidence citations — click one, the log panel scrolls to that exact document and highlights it; tiered recommendations, copyable; "similar past incidents" panel showing what recall retrieved and how it changed the analysis; 👍/👎 + correction box.

**4. Memory.** Incident memories (with their `summary_text`), per-route playbooks, hit counts, confidence, feedback applied — proof that claim #3 is real storage, not a prompt trick.

**Design direction:** dense ops-console, dark, monospace for anything log-shaped, one restrained accent plus semantic severity colors. Motion only on state change. It should look like something an SRE team would leave on a wall monitor — not an AI-gradient landing page.

---

## 6. Data contracts

### 6.1 The three log documents

As specified in §2.1 with §2.5's treatments — the generator emits these shapes verbatim (authentic quirks included), typed properly (BSON Dates, string `usr_id`, real nulls only where Excel damage was repaired). One clean example per collection goes in `SCHEMA.md`. Plus the additive fields the simulator stamps: `seq` (monotonic per `trns_id`), `channel` display name.

### 6.2 Incident document

```json
{
  "incidentKey": "route:eis_marTech_getInteractOffers:TEEIS009:2026-07-24T10:31",
  "status": "analyzing|complete|failed",
  "trnsIds": ["…"], "sessnTknIds": ["…"],
  "firstErrorAt": ISODate, "analyzedAt": ISODate, "durationMs": 21400,
  "errCds": ["TEEIS009", "BS000001/BSYHP003"],
  "journeysInvolved": ["martech_hyper-personalization_offers_fetch"],
  "systemsInvolved": ["EIS", "MARTECH_DWH"],
  "originComponent": "EIS thirdParty/wrapper/Martech route",
  "timeline": [ … ],
  "metrics": { "p95BaselineMs": 480, "p95IncidentMs": 10120, "usersAffected": 14 },
  "rca": { "rootCause": "…", "causalChain": [ … ], "contributingFactors": [ … ],
           "blastRadius": { "journeys": [], "channels": [], "userCount": 14 },
           "evidence": [ObjectId, …], "confidence": 0.86, "unknowns": [ … ] },
  "recommendations": [ { "tier": "immediate|fix|prevent", "action": "…",
                         "ownerSystem": "…", "effort": "S|M|L", "impact": "H|M|L" } ],
  "recalledIncidents": [ … ], "nodeTrace": [ … ], "tokenUsage": { … },
  "feedback": { "verdict": null, "note": null }
}
```

### 6.3 Field glossary

A single `glossary.md` (rendered into LLM prompts and the UI's hover-help): `trns` = transaction, `sessn_tkn` = session token, `cmnd` = command/journey, `chnl` = channel (2001 mobile / 1001 web), `crtd` = created, `stts/sts` = status (both spellings live), `usr_rltnshp_no` = customer relationship number, plus the `err_cd` vocabularies (`BS*` business, `TE*` technical, bare numerics legacy) and known business codes from the sample (`BSYHP003`, `BSPAPL010`, `BSDML050→BSDML024`, `TEEIS009`, `TEY2GSA02`, `BFR003`, `5151`).

---

## 7. Scenario catalogue

Eight scenarios, each grounded in a pattern the sample data actually exhibits (§2.4), each targeting a distinct RCA class. **In every one, the component that throws the loudest error is not the one that caused the problem.**

| id | Cascade | What the agent must figure out |
|---|---|---|
| `eis-martech-brownout` | EIS `thirdParty/wrapper/Martech` route: latency 300ms→10s + `TEEIS009` across sessions → `martech_…_offers_fetch` errors (`BS000001/BSYHP003`) on many dashboards | Loud journey errors are symptoms; origin is one shared downstream route. Incidence + baseline checks prove it. |
| `martech-cif-desync` | Ops transaction "Martech audience refresh" (a *success* doc) at T−45s → `BSYHP003 CIF Is Not Recognized` spikes for a cohort | Link a non-error precursor to the failures. |
| `think360-token-expiry` | `eis_financialfitness_accessToken` renewals fail / JWT `expiry` passes → PFM kyc/summary calls fail simultaneously across sessions (`5151`, 404-inside-success) | Fan-out from a single shared credential; the credential call itself barely registers. |
| `unipay-bbps-brownout` | UNIPAY autopay: business-failure ratio (`responseCode 001`, `BFR003`) climbs over ~3 min while transport stays `success` → billpay journey failures | Layered-status decoding + time-series trend; no status field ever turns red. |
| `gsa-validation-hang` | Insurer validation dependency slows → `gi_gsa_purchase_validate_checks` p95 → 15s → `TEY2GSA02` after timeout | Timeout-shaped failure; origin is the dependency's latency, not the journey's validation code. |
| `demand-loan-improper-response` | CBS loan-discharge dependency returns malformed body → `BSDML024 "received improper response"` wrapped in `BSDML050` | Unwrap the nested `err_dtls` chain; name the innermost cause and the malformed-contract nature. |
| `poison-retry-loop` | One client app replays a malformed `biz_req_input` → identical `5151` technical exceptions repeating for one `usr_id`/session | Distinguish a single-client poison loop from a systemic outage via incidence checks. |
| `eis-gateway-pool-exhaustion` | Connection failures to the EIS gateway host across **all** `eis_*` routes at once → every EIS-backed journey degrades | Widest blast radius; loudest errors are per-journey business exceptions; origin is the shared gateway. |

Each scenario is a **data file** (routes touched, log sequence, timing offsets, statuses, payloads) — not branching code. The agent has no scenario-specific logic anywhere. Document the ground truth per scenario in `/docs` (the agent never sees it) for §11 verification.

---

## 8. Guardrails

1. **No hardcoded answers.** No scenario names in emitted data, no keyword→RCA lookup tables. Acceptance test: rename all scenario ids and rewrite their surface messages to nonsense; RCAs must still be correct.
2. **No mock data in the UI.** Every pixel comes from Atlas.
3. **No extra infrastructure.** No Kafka, Redis, Postgres, Elasticsearch, external vector DB, or external embedding pipeline. Anything added destroys claim #1. If you think you need one, raise it.
4. **Latency budget:** error fired → incident on screen ≤ 30s, target 15s; streaming starts within 2s.
5. **Restart-safe.** Kill any component mid-run; recovery without duplicate or missing incidents.
6. **Offline fallback.** The demo has **two** network dependencies now (Atlas + Grove). `make replay` replays a recorded run from fixtures with zero network. Build it in P6, rehearse with it, and treat it as the venue's primary plan B.
7. **Honest failure.** If the agent can't determine the cause, it says so with what it ruled out. Confidently wrong in front of architects is fatal; "insufficient evidence, here's what I checked" is credible.
8. **`make reset`** returns everything to a clean pre-demo state in one command — including `incident_memory`, `store`, `checkpoints` — so run #1 vs run #2 of the memory demo is reproducible. (§10 trap #7.)

---

## 9. Phases

| Phase | Build | Acceptance test |
|---|---|---|
| **P0** | `PLAN.md`; Atlas project provisioned via script (`/atlas`); collections, TTLs, compound indexes, **lexical search index**, **`autoEmbed` vector index (voyage-4-lite)** created; the two spikes: (a) autoEmbed index+query syntax verified on this cluster/tier, (b) Grove structured-output support verified; health endpoints | Script-provisioned Atlas from zero; a raw-text `$vectorSearch` against a hand-inserted `incident_memory` doc returns it; a schema-constrained Grove call round-trips valid JSON |
| **P1** | `yonosim`: background traffic + all 8 scenarios emitting the §2 shapes; Mongo appender; `seed.py` with §2.5 repair rules; `SCHEMA.md` + `glossary.md` | Seeded sample rows + 500 generated docs pass a shape-validator against `SCHEMA.md`; fire a scenario, see the full cascade joined across three collections under its `trns_id`s; `service_metrics` populating |
| **P2** | Watcher: debounce, signature escalation, idempotency, resume tokens | Fire 3 scenarios rapidly → exactly 3 incident stubs (and a multi-session scenario groups to *one*). Kill watcher mid-cascade, restart → still exact |
| **P3** | LangGraph skeleton: `intake`, `collect`, `correlate`, `verify` — **deterministic only**, LLM nodes stubbed | Correct cross-collection timeline, layered-status classification, and `origin_candidate` for all 8 scenarios with **zero LLM calls** |
| **P4** | LLM nodes + memory: checkpointer, store, hybrid `$rankFusion` recall | ≥7/8 scenarios correct RCA vs documented ground truth. Same scenario fired twice → second run cites the first, measurably faster |
| **P5** | FastAPI + SSE + all four UI views | The §1 core narrative runs start-to-finish touching nothing but the CLI |
| **P6** | Feedback/learn path, memory view, `make replay`, `DEMO.md` (both tracks), polish | Cold machine → clone → `make up && make seed && make demo` → working demo in <5 min by someone who's never seen it; `make replay` works with networking disabled |

---

## 10. Known traps — read before P1

1. **The Log4j MongoDB appender.** The original plan referenced `log4j-mongodb3` on Log4j 2.12.x — an old branch bound to MongoDB driver 3.x that will fight modern drivers and Atlas. Evaluate current Log4j 2.x MongoDB support first; if it can't produce the §2 document shapes cleanly (three differently-shaped streams + a metrics stream), **write a small custom Log4j2 `Appender` plugin** on driver 5.x (~80 lines, full control over document shape — which you want anyway). Decide in P0, record in `DECISIONS.md`.
2. **Atlas is remote.** IP access list must include the demo machine *and* the venue network (or use `0.0.0.0/0` on the throwaway demo project); test from a phone hotspot as the venue proxy. Search/vector indexes take **minutes** to build — create them in P0, never live. Verify the chosen cluster tier supports Atlas Search, Vector Search, and Automated Embedding preview features in its region; record tier/region in `DECISIONS.md`. Budget for `$search`/`$vectorSearch` not being available on the free tier's smallest configs — pick the smallest tier that demonstrably runs everything.
3. **Automated Embedding is public preview.** Index type `autoEmbed`, model `voyage-4-lite`, query with raw text — but preview APIs drift. The P0 spike pins the exact index definition and query syntax against current docs on *your* cluster. Also confirm preview quotas/limits are compatible with demo write rates. **Fallback if the preview misbehaves on demo day:** a thin embedding call to the Voyage API behind the same `recall.py` interface — but this sacrifices the `grep -r embed` beat, so it's a break-glass path only.
4. **Excel already mangled the sample.** `usr_id` float precision loss, `'NULL'` strings, mojibake — §2.5 says which damage the seed repairs and which authentic mess the generator must reproduce. Don't "clean" the authentic mess; it's the demo's realism.
5. **Clock ordering.** Three writers (`TransAdtUser`, `ErrorAdtUser`, `ServiceAdtUser`) with `crtd_on` write-lag; events interleave at ms resolution. Carry a monotonic `seq` per `trns_id`; order by `(strt_time, seq)`. The timeline is the foundation — if it's wrong, everything downstream is wrong.
6. **The debounce window is the difference between a good and a useless demo.** Too short: the agent analyzes the first error of a ten-event cascade. Too long: the demo drags. Configurable; tune against real scenario timings in P2.
7. **Memory demo needs a clean slate.** `make reset` clears `incident_memory`, `store`, `checkpoints` — or run #1 already has memories from rehearsal and the contrast is dead.
8. **`gemini-flash-lite` is a light model.** Deterministic nodes carry the analysis; LLM nodes get tight schema-constrained prompts with the glossary, temperature 0, pinned model, validation + one retry. If the Grove proxy lacks native structured outputs (P0 spike), JSON-mode + pydantic is the path. Rehearse the exact demo flow ten times and log output variance.
9. **Don't let `collect` pull the whole database.** Bounded windows, projections, limits at every rung of the widening ladder. A runaway query mid-demo on a small Atlas tier is a bad look twice over.
10. **The abbreviated field names will confuse the LLM.** `trns_stts` vs `trns_sts`, `cmnd_id`, `usr_rltnshp_no` — always prompt with the glossary (§6.3), and have `correlate` attach decoded, human-named fields to timeline events so LLM nodes read `journey`/`system`/`businessStatus`, not raw abbreviations.
11. **Change streams don't run on time series collections.** The trigger stays on the audit collections; `service_metrics` is analytics-only. Verify against the current server version and note it.

---

## 11. Definition of done

- [ ] `git clone && make up && make seed && make demo` on a clean machine in under 5 minutes (Atlas pre-provisioned by `make atlas-provision`)
- [ ] All 8 scenarios produce correct RCAs vs documented ground truth the agent never sees
- [ ] All six platform capabilities (claim #1) are visibly exercised and named on screen during the core narrative
- [ ] Repeat-fire demonstrably uses memory — faster, higher confidence, cites the prior incident, playbook hit count increments
- [ ] `grep -r embed` across `/agent` finds no embedding client — the Automated Embedding beat holds
- [ ] Every RCA claim traces to specific audit documents, clickable in the UI
- [ ] Kill and restart every component individually mid-demo; clean recovery
- [ ] `make replay` runs the full demo with networking disabled
- [ ] `DEMO.md`: both tracks — 5-min core (exact keystrokes, what to say at each beat, break-glass steps) and 15-min architect deep-dive (index definitions, verify pipelines, checkpoint docs, the grep beat)
- [ ] `ARCHITECTURE.md`: one diagram, the six claims, how each is proven

---

## 12. Decisions locked · items still to verify

**Locked (do not reopen):**
1. **Database:** MongoDB **Atlas cloud** — dedicated throwaway demo project, script-provisioned.
2. **Embeddings:** Atlas Vector Search **Automated Embedding** with Voyage **`voyage-4-lite`**. No embedding code anywhere.
3. **LLM:** **Grove API** (internal OpenAI-compatible proxy), model **`gemini-flash-lite`**, temperature 0, role abstraction retained via env vars.
4. **Audience:** tech architects & builders → dual-track `DEMO.md`, inspectable pipelines, capability badges.
5. **Java app:** stays a **simulator** (`yonosim`), one process, three audit streams + metrics, YONO-shaped.
6. **Platform scope:** the story is **all of** Change Streams + Vector Search (auto-embedded) + agent memory + **Atlas full-text Search** + **time series** — every one earns explicit screen time.

**Verify in P0 (spikes, results into `PLAN.md` + `DECISIONS.md`):**
- Exact `autoEmbed` index definition + text-query syntax on the provisioned cluster; preview tier/region/quota constraints.
- Grove proxy capabilities: structured outputs / function calling / JSON mode, context limits, rate limits; confirm the exact model string.
- Log4j2 appender choice (current module vs custom plugin).
- Change-streams-on-time-series restriction on the cluster's server version.
- `$rankFusion` availability on the cluster's server version (requires a recent server; if unavailable on the chosen tier, implement reciprocal-rank fusion of the two arms in `recall.py` and say so on the node badge).

---

**Start by producing `PLAN.md` with the P0 spike results. Do not write implementation code until that's confirmed.**