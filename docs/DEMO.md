# DEMO.md — NOVA 2.0 RCA on MongoDB Atlas

Two tracks: a **5-minute core** (build backwards from the 90-second narrative) and a **15-minute architect
deep-dive**. Audience: architects and builders. One datastore on screen the whole time.

**One-command guided run:** `make demo-live` (`scripts/demo.sh`) executes the whole 5-minute core —
clean slate → stack up → background traffic → fires the scenario over the API → waits on the autonomous
incident → holds out of the 120s merge window → re-fires for the memory beat → `grep embed` beat —
pausing at each presenter cue (`--auto` for unattended rehearsal, `--scenario <id>` to swap the story).

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
make replay         # offline fallback
make down           # stop agent + UI
make atlas-provision# verify collections + indexes (idempotent)
```
