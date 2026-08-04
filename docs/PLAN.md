# NOVA 2.0 RCA Demo — Execution Plan

**Status: delivered and verified end-to-end.** This is the plan committed at P0 (brief §0.1),
annotated with what shipped. Reality corrections and version pins live in `DECISIONS.md`;
the demo scripts in `DEMO.md`; the claim→proof map in `ARCHITECTURE.md`.

## Reading of the brief

We are proving **MongoDB Atlas is the unified data platform for agentic AI**. One database serves
every workload an RCA agent needs — operational document store, Change Streams event bus, time-series
metrics, Atlas Search (lexical), Vector Search with **Automated Embedding** (`voyage-4-lite`, no
embedding client in code), durable agent memory (LangGraph checkpointer + store), and `$rankFusion`
hybrid retrieval. The log-RCA use case is the vehicle; every decision is graded against the six claims
(`ARCHITECTURE.md`). It is **not** a chatbot: the agent wakes on a data change, runs autonomously, and
publishes a report.

The 90-second core: a live NOVA ops board → presenter fires `eis-martech-brownout` in the Java CLI →
Change Streams wake the agent unprompted → the LangGraph DAG lights node by node → RCA names the
**shared EIS `thirdParty/wrapper/Martech` route** as origin (not the loud journey errors) with cited,
clickable audit docs → tiered recommendations. Fire again → memory recall short-circuits to a
confident RCA in a fraction of the time, citing the first incident.

## Committed architecture

```
Java CLI (novasim, Log4j2 custom Mongo appender)
    → MongoDB Atlas (nova_rca): audit_transaction/error/service, service_metrics (TS),
      incidents, incident_memory, kb_docs, checkpoints, checkpoint_writes, store, feedback, agent_state
    → Change Streams wake the Agent (Python): watcher → LangGraph 9-node graph
      (intake→collect→correlate→recall→hypothesize→verify→rca→recommend→persist; verify⟲collect;
       recall→confirm warm short-circuit) → memory (MongoDBSaver + MongoDBStore) → hybrid recall ($rankFusion)
    → FastAPI + SSE → React ops console (Ops board · Agent Workflow · Incident detail · Memory)
```

Two reality corrections carried from the brief (details in `DECISIONS.md`):
1. **`$rankFusion` is single-collection.** The brief's "one aggregation over `incident_memory` + `kb_docs`"
   is impossible. Fix: `recall` runs **two** `$rankFusion` aggregations (one per collection), each fusing a
   `$vectorSearch` arm and a `$search` arm; the UI shows both arms and the fused ranking.
2. **No stock Log4j Mongo appender fits.** `log4j-mongodb4` maps to a fixed layout and cannot emit our four
   differently-shaped documents. Fix: a custom `@Plugin` appender on `mongodb-driver-sync` 5.x.

## Phase plan & acceptance tests (all met)

| Phase | Deliverable | Acceptance | Result |
|---|---|---|---|
| **P0** | Atlas collections + 6 search/vector indexes; Grove + autoEmbed spikes; `/api/health` | indexes READY; autoEmbed round-trips raw-text query; Grove round-trips schema-valid JSON; health green | ✅ 6/6 indexes READY; autoEmbed `voyage-4-lite` returns ranked docs; Grove `gpt-5.4-mini` `json_schema` OK |
| **P1** | novasim (Java 21) + custom appender + 8 data-only scenarios; `seed.py`; SCHEMA/glossary | `make sim` fires; validator passes on seeded + ≥500 generated; 3-collection join on one `trns_id` | ✅ jar builds; brownout emits TEEIS009→BS000001/BSYHP003; no real sbi.co.in hosts |
| **P2** | resume-safe watcher, debounce, idempotency | 3 scenarios→3 stubs; multi-session→1 stub; kill mid-cascade→no dupes | ✅ dedup merges one cascade→one incident; unique `incidentKey` claim is restart-safe |
| **P3** | deterministic graph (intake/collect/correlate/verify/persist) | layered-status decode + origin≠loudest, zero LLM | ✅ origin = `eis_marTech_getInteractOffers`, distinct from loudest `BS000001` |
| **P4** | LLM nodes + memory + hybrid `$rankFusion` recall | RCA origin correct; run-2 recalls run-1, playbook count 2 | ✅ conf 0.8 cold; run-2 warm short-circuit 5.4× faster, conf 0.9, cites run-1 |
| **P5** | FastAPI + SSE + 4-view UI | core narrative end-to-end via CLI; incident card unprompted; workflow lights node-by-node | ✅ verified in-browser: autonomous incident, badges, live pipelines, token meter |
| **P6** | learn path, `make reset`/`replay`, DEMO/ARCHITECTURE docs | clean-machine `make up && make seed && make demo`; reset clean board | ✅ `make up`/`reset` verified; docs delivered |

## P0 spike results (the two hard gates)

- **Spike A — autoEmbed (public preview).** Index type `autoEmbed`, model `voyage-4-lite`, `path` on the
  text field; query with `$vectorSearch: { query: { text: "…" }, numCandidates, limit }` — **never** a
  `queryVector`, **never** an embedding API call. Verified on the live M30/8.3.7 cluster: a hand-inserted
  `incident_memory` doc is returned by a raw-text semantic query; embeddings live in the internal
  `__mdb_internal_search` collection. Managed via the **Atlas Admin API** (the cluster rejects Atlas Search
  DB commands); the driver still `$search`/`$vectorSearch`-queries normally.
- **Spike B — Grove structured output.** `gpt-5.4-mini` over the Grove OpenAI-compatible gateway (custom
  `api-key` header, temperature 0) round-trips `response_format: json_schema` (strict) → pydantic-validated.
  The ladder degrades `json_schema → json_object → prompt+retry`; the winning rung is pinned in
  `GROVE_STRUCTURED_MODE`. `gemini-flash-lite` (brief default) is **not** a valid Grove deployment — the role
  abstraction made this a one-line env swap (see `DECISIONS.md`).

## Guardrails honored
No hardcoded answers; no scenario names in emitted data (generic effect interpreters); RCA cites real doc
`_id`s; origin differs from the loudest error; **no embedding client in `/agent`** (`grep -ri embed agent/`
is a scripted demo beat — the word appears only in index-definition JSON under `/atlas`).
