# DECISIONS

One line per non-obvious choice, with the reason. Version pins at the bottom.

## Platform / infrastructure
- **Single Atlas cluster, single DB `nova_rca`.** One datastore on the architecture slide is the whole
  point (claim #1). Cluster: `financial-compliance-assistant-db`, **M30 Gen2, MongoDB 8.3.7, AWS
  ap-south-1**, shared with other demo DBs — the agent isolates strictly inside `nova_rca`.
- **Used the operator's existing M30 cluster, not a fresh M10.** The provided API key is `ORG_MEMBER` +
  `GROUP_OWNER` on `MDB_EDU` only (cannot create projects); the real work cluster lives in the Sangram
  project. M30/8.3.7 exceeds every requirement (autoEmbed needs M10+, `$rankFusion` needs 8.0+), so no
  fallback was needed. Auto-scaling capped at M30.
- **Search/vector indexes are managed via the Atlas Admin API, not driver `createSearchIndex`.** This
  cluster rejects Atlas Search *database commands* (`listSearchIndexes` errors "requires additional
  configuration"). The Admin API (HTTP digest auth) creates/polls indexes cleanly; the driver still runs
  `$search`/`$vectorSearch`/`$rankFusion` queries normally. Helper: `agent/nova_agent/atlas_admin.py`.
- **`versionReleaseSystem` irrelevant here** — the cluster is already 8.3.7 (CONTINUOUS-equivalent), so
  `$rankFusion` (8.0+) and `$scoreDetails` work natively; no in-app RRF fallback needed.

## Reality corrections vs the brief (brief §0.4)
- **`$rankFusion` is single-collection.** Verified against MongoDB docs + live cluster. The brief's single
  fusion over `incident_memory` + `kb_docs` is impossible. **Fix:** `recall` runs two `$rankFusion`
  aggregations (one per collection), each fusing a `$vectorSearch` (autoEmbed) arm and a `$search` lexical
  arm; the UI inspector shows both arms + fused ranking. This required adding **lexical** search indexes on
  `incident_memory` and `kb_docs` (brief listed lexical indexes only on audit collections).
- **No stock Log4j Mongo appender fits.** `log4j-mongodb4` maps LogEvents to a fixed layout and cannot emit
  four differently-shaped raw documents. **Fix:** custom `@Plugin(name="NovaMongo")` appender (~AbstractAppender)
  on `mongodb-driver-sync` 5.x, inside an `AsyncAppender`; bounded 10k queue, drop-oldest, batch flush at
  100 docs / 200ms, exponential-backoff retry, never throws.
- **Change Streams are NOT supported on time-series collections** (verified through 8.x). Triggers stay on
  `audit_error` + `audit_service`; `service_metrics` is read-side analytics only.

## LLM
- **Grove model = `gpt-5.4-mini`, not `gemini-flash-lite`.** Grove has **no** Gemini deployment
  (`DeploymentNotFound`); `gemini-flash-lite` from the brief is not routable. `gpt-5.4-mini` validated:
  plain call, temperature 0 accepted, and strict `json_schema` structured output round-trips. The role
  abstraction (`LLM_FAST_MODEL` / `LLM_REASONING_MODEL`) made this a one-line `.env` change — architecture
  untouched. Any OpenAI-compatible endpoint works via the same three env vars.
- **Grove auth is a custom `api-key` header, not Bearer.** The OpenAI SDK is configured with
  `default_headers={"api-key": …}` and a dummy `api_key`. Temperature is omittable (some models reject it);
  `GROVE_SEND_TEMPERATURE` empty → omitted.
- **Structured-output ladder:** `json_schema → json_object → prompt+retry`, selected by
  `GROVE_STRUCTURED_MODE` (pinned to `json_schema`). Every rung stays in `llm.py` so a weaker endpoint still
  works. Deterministic nodes carry the analysis; the LLM narrates and ranks over evidence the code
  established — the division of labor is itself a talking point.

## Agent design
- **9 fixed nodes + one warm short-circuit.** `intake→collect→correlate→recall→hypothesize→verify→rca→
  recommend→persist`, `verify⟲collect` (widen once if all hypotheses score < 0.34), and a **`recall→confirm`**
  warm path: a confident memory hit (recalled incident or playbook with a confirmed fix) skips the LLM
  hypothesize/verify/rca/recommend and confirms the recurrence deterministically. Run-2 measured **5.4×
  faster** (3.3s vs 17.7s), higher confidence (0.9 vs 0.8), cites run-1 — claim #3.
- **Origin ≠ loudest, deterministically.** `correlate` picks the earliest **downstream** (`audit_service`)
  failure as origin, explicitly distinct from the highest-count journey error code. The LLM cannot override
  this — it explains it. Claim #5.
- **Incidence check anchors on the deterministic origin `srvc_id`, not the LLM's phrasing.** The verify
  aggregation matches `srvc_id ∈ {implicatedComponent, origin.srvcId}` so scoring is robust to how the LLM
  names the component.
- **State carries raw docs with ObjectId→str stripped (`strip_oid`), datetimes kept.** The MongoDBSaver
  checkpointer msgpack-encodes state and cannot serialize `ObjectId`; datetimes it handles, and `collect`/
  `correlate` need them for `(strt_time, seq)` ordering and duration.
- **`$rankFusion` fused score surfaced via `{$meta:"score"}` + `scoreDetails`.** Aliased to `score` so the
  UI reads one field across arms; fused RRF scores ≈ 0.03 render in the inspector.
- **Incident dedup: one cascade = one incident.** The `audit_error` and `audit_service` watches fire
  different signatures for the same cascade; dispatch stores `trnsIds` at claim time and merges a new
  trigger into any recent incident sharing a `trns_id`. The flusher is single-threaded, so the first
  incident's run completes before the second trigger is processed.

## API / UI
- **`make up` runs the local stack (venv uvicorn + Vite), not docker.** Fastest, most reliable path for a
  live demo; Atlas is cloud so no DB container is needed. `docker-compose.yml` (service `api` + `ui` +
  optional `novasim` profile) is the documented containerized alternative.
- **`/api/metrics?window=` accepts duration strings (`15m`,`300s`,`2h`) and matches service flexibly**
  (exact / prefix / contains / trimmed `meta.system`) so journey-prefix tiles and system tiles
  (`EIS`,`MARTECH`, `' UNIPAY'`) all resolve. The UI sent `window=15m`; the original `int` typing 422'd.
- **`/api/logs` returns a merged, source-tagged, time-sorted flat array** (`MergedLog[]`), matching the UI
  contract; a keyed object 422/​crashed the Incident Detail view.
- **React `ErrorBoundary` wraps the view switch.** One view error shows a fallback and keeps the
  header/nav — a white-screen is the worst live-demo failure. Resets on tab change.
- **`POST /api/scenarios/{id}/fire` writes `agent_state._id:"sim:command"`; novasim polls every 2s.** Keeps
  novasim a pure CLI/simulator (no HTTP server inside it); the CLI stays the primary fire path.
- **Watcher significance gate: benign noise stays background.** The authentic noise floor (occasional
  single business exceptions like `BSPAPL010`, sporadic errors) must NOT each spawn a full RCA incident or
  the board floods. Dispatch runs the graph only when the trigger is significant — a downstream
  `audit_service` failure (`trns_sts -2` / `^TE`) OR a burst of **≥2 distinct `trns_id`** sharing the
  signature. Sub-threshold lone business errors are logged to the firehose, not escalated. All 8 demo
  scenarios burst or hit a downstream failure, so every scenario still triggers; verified live: firing
  `eis-martech-brownout` yields exactly ONE incident (origin `eis_marTech_getInteractOffers`), not the 5
  it produced before the gate.
- **Significance gate refined to hard vs soft (silent business failures).** A `unipay-bbps-brownout`
  is transport-success / business-fail with NO audit_error and NO red status — the original watcher
  never saw it. Fix: a third `audit_service` watch arm matches the UNIPAY payload (`"responseReason":"Failure"`;
  generic `"success":false` is deliberately NOT matched — it is the 5% noise floor), and the gate now runs the graph when the trigger is **hard** (transport `-2` /
  `^TE`, always an incident even singly) OR a **burst** (≥2 distinct trns). Silent single business
  failures stay noise; the brownout ramp escalates. Verified live: unipay fires ONE incident,
  `faultClass: business`.
- **RCA classifies faultClass: technical vs business.** `correlate` pre-classifies the origin
  deterministically (transport/`TE`/numeric/transformation/timeout/token/pool → technical; `BS*`/
  compliance/data → business); the `rca` LLM confirms and explains (`faultReason`). Surfaced as a badge
  on the incident card + detail. A downstream transformation/timeout/credential failure is TECHNICAL
  even when it surfaces to the user as a business code (e.g. brownout → technical though users see
  BS000001). 6 of 8 scenarios are technical, 2 business — the demo shows both, and the RCA names which.
- **Scenario context is data, served to the UI.** Each `scenarios/<id>.json` carries `title`,
  `faultClass`, `description`, `expectedOrigin`, `decoy`, `analyzes` (collections). `/api/scenarios`
  returns them; the Ops board renders an expandable context panel per scenario. The agent still NEVER
  reads these (guardrail intact); Jackson set to ignore unknown fields so novasim tolerates the metadata.
- **`collectionsAnalyzed` surfaced.** `persist` records which collections the agent queried and their
  role (audit_transaction/error/service, service_metrics, incident_memory, kb_docs, store) + counts; the
  Incident detail shows a "Collections analyzed — one Atlas DB" panel (claim #1 made concrete per incident).
- **`make down` kills by port, not just pid.** The old pid capture grabbed an exited subshell (nohup
  detached vite), so `down` left the UI up. Now `down` kills whatever listens on AGENT_PORT/UI_PORT plus
  `pkill` the vite/agent processes — reliable regardless of how they were started.
- **Errors correlate with `Sample Log Data.xlsx` (verified).** The workbook's codes — `TEEIS009`
  "Response Transformation failed" on `eis_marTech_getInteractOffers` (twice, systemic), `BS000001`
  wrapping `BSYHP003`/`BSPAPL010`/`BSDML050→BSDML024`, `TEY2GSA02` & `5151` (both `TECHNICAL_EXCEPTION`),
  UNIPAY transport-success/business-fail — are exactly what the 8 scenarios reproduce. The workbook's own
  `err_typ` (BUSINESS vs TECHNICAL) grounds the faultClass split.
- **Investigate chat is a first-class entry point (INVESTIGATE tab).** `POST /api/chat`: a vision LLM
  (`LLM_VISION_MODEL=gpt-4o-mini`, probed live on Grove — strict `json_schema` + `image_url` parts work)
  triages the description/screenshot into signals (journeys from the 15-journey catalog, err codes, ids,
  timeframe); a deterministic ladder finds evidence (explicit ids → codes → errored journey txns →
  Atlas Search over `err_dscrptn` ONLY when triage produced no structured signal — a named journey with
  no evidence gets the honest "no matching failures", never a fuzzy match); a recent overlapping incident
  is cited instead of re-run; otherwise the chat claims a `chat-<sess8>:<minute>` incident and runs the
  SAME graph in a background thread, replying over SSE (`type:"chat"`). Chat history lives in Atlas
  (`chat_sessions`; screenshots in `chat_images`, TTL 7d). Follow-up turns answer over the linked
  incident doc with one `llm.converse` call — no re-investigation.
- **`/api/architecture` powers the ARCHITECTURE tab.** Static app topology (NOVA App / EIS Gateway /
  UNIPAY BBPS / Metrics emitter) + live 60s ingestion rates per app and per hot collection, `collStats`
  docs/size, a **sampled live query latency** per collection (timed indexed `find_one` per poll), a live
  one-`trns_id`-across-services correlation example, and watcher heartbeat/resume state. Per-collection
  sampling is parallelized (ThreadPoolExecutor) — sequential WAN round-trips blew the poll budget (7s→0.9s).
- **Every incident carries the multi-service story.** `correlate` stamps each timeline event with
  `sourceApp` (NOVA App / EIS Gateway / UNIPAY BBPS from collection + `systm_nm`); `persist` writes a
  `correlation` block (services→collections→docs, join-key counts); Incident detail renders it as a
  strip above the swimlanes ("N documents · M Java services → K collections · joined on trns_id + sessn_tkn_id").
- **Same-downstream-family merge in dispatch.** Two srvc_id signatures on the same system family
  (`unipay_*`, `eis_*`) bursting within 120s merge into one incident even when their trns_ids are
  disjoint (different journeys hit different routes of the same failing backend). Verified: the unipay
  brownout that once produced 2 incidents now yields exactly 1.
- **Cascade merge widened to session overlap.** Downstream latency can shift the journey-error window
  past its service window (disjoint trns sets, same users); dispatch now merges on trns_id OR
  sessn_tkn_id overlap within 120s. Verified: `login-failures` = exactly 1 incident (was 2).
- **Every investigation query is on the incident doc (`agentQueries`).** `collect` records each literal
  filter it runs (+ purpose + workload tag), `persist` appends the hybrid `$rankFusion` recall pipeline
  and both verify aggregations. Incident detail renders them expandable with workload badges —
  "TIME SERIES · bucketed ts-range scan + $percentile", "$rankFusion — Vector Search + Atlas Search" —
  so the correlation/efficiency story is on screen, not narrated. Excluded from the list projection.
- **Evidence citations resolve to the actual document.** `persist` stores `originDocId`; timeline events
  carry their `_id`; `/api/logs?ids=` fetches cited docs directly. Clicking an evidence chip (or any
  swimlane dot) highlights, auto-expands, and scrolls to the full JSON doc in Raw logs — fetching it
  on miss instead of silently doing nothing. TTL-expired citations get an explicit note.
- **Time-series + indexing tuned per MongoDB schema-design guidance** (mongodb-schema-design skill):
  `service_metrics` coarsened to `granularity: "minutes"` via collMod (per-series rate ~0.25–2/s →
  better bucket fill than "seconds"); secondary index `{meta.service:1, ts:1}` added because the
  auto `{meta, ts}` index covers whole-meta equality only, not the subfield our hot queries filter on.
  Query-driven regular indexes added (each maps to a named live query, none redundant-prefix):
  TXN `{usr_id, strt_time}` + `{usr_rltnshp_no, strt_time}` (chat id ladder), SVC `{err_cd, crtd_on}`
  (chat codes ladder), incidents `{createdAt}` (merge windows/sorts). Chat id ladder now queries TXN
  only (ERR/SVC join later via indexed trns_id); architecture `systm_nm` regex → exact `$in` (keeps
  the authentic `' UNIPAY'` variant). All verified with `explain()`: IXSCAN / `meta.service_1_ts_1`.

## Verification results
- **Live change-stream trigger:** inserting a cascade (no API call) produced an autonomous incident; SSE
  streamed the full 9-node lifecycle with all five capability badges. Claim #2, #6.
- **Hybrid recall:** vector arm (autoEmbed, top≈0.51) + lexical arm (exact TEEIS009/BSYHP003) + fused
  ranking all return real scores. Claim #4.
- **Memory:** run-1 cold (9 nodes, conf 0.8, 0 recalled); run-2 warm (`…recall→confirm→persist`, 5.4×
  faster, conf 0.9, cites run-1, playbook `seenCount` 2). Claim #3.
- **UI in-browser:** ops board tiles with live sparklines (Offers p95 9.58s, 100% err), autonomous incident
  card, workflow DAG with badges + timings + token meter (3,711 tok / $0.0008), literal `$rankFusion`/
  `$vectorSearch` + verify pipelines in the inspector, incident detail swimlanes with ORIGIN flagged
  distinct from symptoms, clickable evidence, tiered recommendations. Claims #1,#4,#5,#6.
- **Automated tests (`make test`):** 32 unit tests over the deterministic core (layered-status decode,
  nested `err_dtls` unwrap, transport/business classification, route derivation, debounce windows +
  escalation + significance sources, recall/verify routing, window parsing, BSON serialization) — all
  green, no network. `data/validate_shapes.py` passes on seeded docs. `make check-no-embed` passes.
- **Scenario RCA eval (`make eval`, `agent/tests/eval_scenarios.py`):** all **8/8** scenario classes name
  the correct origin *family* and never the loud decoy — brownout→`eis_marTech_getInteractOffers` (not
  BS000001), cif-desync→martech (precursor), think360→`eis_financialfitness_accessToken` (not 5151),
  unipay→`unipay_…_pendingbills` (no red status), gsa→`gi_gsa_purchase_validate_checks`,
  demand-loan→`cbs_loan_discharge_manage` (not the BSDML050 wrapper), poison-loop→single journey with
  honest low confidence 0.22, gateway→an `eis_` route. Claim #5 across every class.

## Version pins
- **Java** Temurin 21.0.12 · Maven compiler release 21 · **picocli** 4.7.6 · **Log4j2** 2.24.3 ·
  **mongodb-driver-sync** 5.2.1 · **jackson-databind** 2.17.2 · maven-shade 3.6.0 +
  log4j-transform-shade-extensions 0.2.0 (generates `Log4j2Plugins.dat`).
- **Python** 3.12 (venv via `uv`) · **langgraph** 1.2.9 · **langgraph-checkpoint-mongodb** 0.4.0 ·
  **langgraph-store-mongodb** 0.3.0 · **langchain-openai** 1.4.1 · **openai** 2.48.0 · **pymongo** 4.16.0 ·
  **fastapi** 0.139.2 · **uvicorn** 0.51.0 · **sse-starlette** 3.4.6 · **pydantic** 2.13.4 · **openpyxl** 3.1.5.
- **UI** Node 22.15 · React 18.3 · Vite 5.4 · TypeScript 5.5 · Tailwind 3.4 · no chart/graph libraries
  (hand-rolled SVG DAG + inline sparklines).
- **Atlas** cluster M30 Gen2, MongoDB 8.3.7 · autoEmbed model `voyage-4-lite` (1024-dim) · `$rankFusion`
  native (8.0+).
