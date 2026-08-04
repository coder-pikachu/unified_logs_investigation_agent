# NOVA 2.0 RCA Demo — Collection Schemas

Single Atlas DB `nova_rca`. This document defines the shape of every collection
the demo reads or writes, and gives one **real, live example document per audit
collection** pulled from the seeded data (`data/seed.py`). It is the reference
for the seed loader, the shape validator (`data/validate_shapes.py`), the
generator (novasim) and the agent.

Conventions:

- Timestamps (`strt_time`, `end_time`, `crtd_on`, `err_time`) are stored as BSON
  `Date` in **UTC**. Source data is IST (`+05:30`); e.g. IST `16:09:00.547`
  becomes UTC `10:39:00.547`.
- `usr_id` is a **19-digit string** (Excel float-mangling is repaired by the
  seed loader; the generator emits it clean).
- Spelling drift is **intentional and preserved**: `trns_stts` (transaction,
  double-t) vs `trns_sts` (service, single-t).
- `systm_nm` keeps its authentic leading space: `' UNIPAY'`.
- `'NULL'` **literal strings** are kept in `biz_err_cd_*` / `biz_err_cd_*_msg` /
  `trace_id` / `nfrchk` — the real system emits them and the agent must cope.
- JSON payload fields (`biz_req_input`, `biz_resp_output`, `srvc_rqst`,
  `srvc_rspn`, `err_dtls`) are stored **as strings**, and may be double-encoded.
- `seq` is a monotonic `int` per `trns_id` (ordered by event time), added by the
  loader/generator to give a stable ordering independent of `crtd_on`.
- The primary correlation key across all three audit collections is `trns_id`;
  `sessn_tkn_id` groups a user session. `trace_id` is unreliable.

---

## `audit_transaction` — one document per journey action / API call

| Field | Type | Meaning |
|---|---|---|
| `_id` | ObjectId | Mongo id |
| `msg_id` | int | source message id |
| `trns_id` | str | transaction id — primary join key |
| `sessn_tkn_id` | str | user session token |
| `clnt_ip_addr` | str | client IP |
| `req_no` | str | request number (hex or `novaweb_…` on web) |
| `usr_rltnshp_no` | str | customer relationship number |
| `trns_stts` | str | `"error"` \| `"success"` (double-t spelling) |
| `strt_time` | Date | call start (UTC) |
| `end_time` | Date | call end (UTC); duration = `end_time − strt_time` |
| `usr_id` | str | 19-digit user id |
| `usr_typ` | str | `"ETB_CUSTOMER"` |
| `cmnd_id` | str | journey/feature id, `domain_module_feature_action` |
| `chnl_id` | int | `2001` (mobile) \| `1001` (web) |
| `biz_req_input` | str (JSON) | business request payload |
| `biz_resp_output` | str (JSON) | business response, often double-encoded |
| `crtd_by` | str | `"TransAdtUser"` |
| `crtd_on` | Date | write time (UTC; may lag/reorder) |
| `trace_id` | str | mostly `"NULL"`, occasionally a hex trace id |
| `nfrchk` | str | `"NULL"` |
| `seq` | int | monotonic per `trns_id` |
| `channel` | str | `"mobile"` \| `"web"` (derived from `chnl_id`) |

Live example (demand-loan closure, which failed):

```json
{
  "_id": "6a63b06036cfeacd75e834e4",
  "msg_id": 61461911,
  "trns_id": "1783420740536DIwM4ptiVvf63ea51",
  "sessn_tkn_id": "1783420522946ycnq6WzOhmD647e38",
  "clnt_ip_addr": "10.191.199.68",
  "req_no": "10e2154079f011f1bd8bbdf2f4da8c8b",
  "usr_rltnshp_no": "85002721166",
  "trns_stts": "error",
  "strt_time": "2026-07-07T10:39:00.547000+00:00",
  "end_time": "2026-07-07T10:39:12.295000+00:00",
  "usr_id": "1730709013340810605",
  "usr_typ": "ETB_CUSTOMER",
  "cmnd_id": "lending_demand_demand-loan-closure_manage",
  "chnl_id": 2001,
  "biz_req_input": "{\"refNo\": \"SBIY220260707154014913oTD\", \"action\": \"Y\"}",
  "biz_resp_output": "{}",
  "crtd_by": "TransAdtUser",
  "crtd_on": "2026-07-07T10:39:12.297000+00:00",
  "trace_id": "2bab76aa84754997be0dc71e40f050ef",
  "nfrchk": "NULL",
  "channel": "mobile",
  "seq": 1
}
```

---

## `audit_error` — one document per error event

Sheet name `"audit error "` has an authentic trailing space.

| Field | Type | Meaning |
|---|---|---|
| `_id` | ObjectId | Mongo id |
| `msg_id` | int | source message id |
| `trns_id` | str | join key |
| `sessn_tkn_id` | str | session token |
| `err_cd` | str | error code — `BS*` business, `TE*` technical, or numeric legacy (`"5151"`) |
| `err_typ` | str | `"BUSINESS_EXCEPTION"` \| `"TECHNICAL_EXCEPTION"` |
| `err_dscrptn` | str | human-readable description (source typos preserved) |
| `err_dtls` | str (JSON) | keyed by business error code, may **nest**; `"NULL"` for many technical errors |
| `crtd_by` | str | `"ErrorAdtUser"` |
| `crtd_on` | Date | write time (UTC) |
| `err_time` | Date | error time (UTC) |
| `usr_id` | str | 19-digit user id |
| `biz_err_cd_1..5` | str | flattened business codes; unused slots are `"NULL"` |
| `biz_err_cd_1_msg..5_msg` | str | matching messages; unused slots are `"NULL"` |
| `seq` | int | monotonic per `trns_id` |

Live example (nested `BSDML050 → BSDML024` demand-loan chain; the innermost code
names the real dependency failure):

```json
{
  "_id": "6a63b06036cfeacd75e834ee",
  "msg_id": 10886129,
  "trns_id": "1783420740536DIwM4ptiVvf63ea51",
  "sessn_tkn_id": "1783420522946ycnq6WzOhmD647e38",
  "err_cd": "BS000001",
  "err_typ": "BUSINESS_EXCEPTION",
  "err_dscrptn": "Business Exception Occured",
  "err_dtls": "{\"BSDML050\":{\"data\":{\"BSDML024\":{\"data\":{\"loan_discharge\":\"received improper response\"},\"message\":\"We regret that your Demand Loan request could not be processed due to technical issue. Please try again after some time.\"}},\"message\":\"Your Demand Loan closure request has failed. Kindly visit branch for further assistance.\"}}",
  "crtd_by": "ErrorAdtUser",
  "crtd_on": "2026-07-07T10:39:12.298000+00:00",
  "err_time": "2026-07-07T10:39:12.295000+00:00",
  "usr_id": "1730709013340810605",
  "biz_err_cd_1": "BSDML050",
  "biz_err_cd_1_msg": "Your Demand Loan closure request has failed. Kindly visit branch for further assistance.",
  "biz_err_cd_2": "NULL",
  "biz_err_cd_2_msg": "NULL",
  "biz_err_cd_3": "NULL",
  "biz_err_cd_3_msg": "NULL",
  "biz_err_cd_4": "NULL",
  "biz_err_cd_4_msg": "NULL",
  "biz_err_cd_5": "NULL",
  "biz_err_cd_5_msg": "NULL",
  "seq": 1
}
```

---

## `audit_service` — one document per downstream/surrounding-system call

| Field | Type | Meaning |
|---|---|---|
| `_id` | ObjectId | Mongo id |
| `msg_id` | int | source message id |
| `trns_id` | str | join key |
| `sessn_tkn_id` | str | session token |
| `trns_sts` | str | `"success"` \| `"0"` (ok) \| `"-2"` (failure) — single-t spelling |
| `err_cd` | str \| int | mixed: `200`, `1`, `"TEEIS009"`, or `""` (empty) |
| `err_msg` | str | e.g. `"No data found"`, `"Failure"`, `"Response Transformation failed."`, or `""` |
| `usr_id` | str | 19-digit user id |
| `srvc_rqst` | str (JSON) | downstream request payload |
| `srvc_rspn` | str (JSON) | downstream response; UNIPAY `{"head":…,"reason":{responseCode,…}}`, EIS `{"ERROR_CODE","EIS_RESPONSE":{status_code,success,message}}` or `{"TXN_TYPE","EIS_PAYLOAD"}` |
| `srvc_id` | str | downstream operation id |
| `systm_nm` | str | `" UNIPAY"` (leading space) \| `"EIS"` |
| `api_url` | str | full downstream URL |
| `rqst_id_sent` | str | downstream request id sent |
| `rqst_id_rcvd` | str | downstream request id received |
| `crtd_by` | str | `"ServiceAdtUser"` |
| `crtd_on` | Date | write time (UTC) |
| `strt_time` | Date | call start (UTC) |
| `end_time` | Date | call end (UTC); duration = `end_time − strt_time` |
| `seq` | int | monotonic per `trns_id` |

Live example (UNIPAY autopay pending-bills — **layered status**: `trns_sts`
reads `"success"` while the payload carries `responseCode 001 / BFR003`; note the
`" UNIPAY"` leading space):

```json
{
  "_id": "6a63b06036cfeacd75e834f1",
  "msg_id": 33447412,
  "trns_id": "1783421066261n9ckREqe6Iy63ea51",
  "sessn_tkn_id": "1783421014768HtDoXQCpsCZ647e38",
  "trns_sts": "success",
  "err_cd": 1,
  "err_msg": "Failure",
  "usr_id": "1730709013340810605",
  "srvc_rqst": "{\"head\": {\"ts\": \"2026-07-07T16:14:28+05:30\", \"agentId\": \"\", \"requestId\": \"SB41202607070414281e26a683446541c5b\"}, \"billerDetails\": {\"id\": \"\", \"category\": \"\"}, \"customerDetails\": {\"cif\": \"00000085002555889\", \"email\": \"tdcapp@gmail.com\", \"mobile\": \"9912303993\", \"countryCode\": \"+91\"}, \"standingInstruction\": {\"id\": \"\"}}",
  "srvc_rspn": "{\"head\": {\"ts\": \"2026-07-07T16:14:28+05:30\", \"agentId\": \"\", \"requestId\": \"SB41202607070414281e26a683446541c5b\"}, \"reason\": {\"responseCode\": \"001\", \"responseReason\": \"Failure\", \"complianceReason\": \"BFR003\", \"complianceRespCd\": \"No bill data available\"}}",
  "srvc_id": "unipay_payment_billpay_autopay_pendingbills",
  "systm_nm": " UNIPAY",
  "api_url": "https://10.176.57.27:4443/bbps-autopay-service/upcomingBills",
  "rqst_id_sent": "SB41202607070414281e26a683446541c5b",
  "rqst_id_rcvd": "SB41202607070414281e26a683446541c5b",
  "crtd_by": "ServiceAdtUser",
  "crtd_on": "2026-07-07T10:44:28.177000+00:00",
  "strt_time": "2026-07-07T10:44:28.081000+00:00",
  "end_time": "2026-07-07T10:44:28.173000+00:00",
  "seq": 2
}
```

> Note: `api_url` values in the seeded sample retain the source UAT hosts
> (`eissiuat.sbi.co.in`, `10.176.57.27:4443`). The **generator** (novasim) only
> ever emits lookalike hosts (`eis-uat.internal`, `unipay-uat.internal:4443`)
> and fresh `10.x` IPs — real hosts are never hardcoded in generated data.

---

## `service_metrics` — time-series (P0 collection)

Time-series collection with `timeField: ts`, `metaField: meta`. One point per
downstream call and per journey action.

| Field | Type | Meaning |
|---|---|---|
| `ts` | Date | event timestamp (UTC) |
| `meta.service` | str | `srvc_id` (downstream) or `cmnd_id` (journey) |
| `meta.system` | str | `systm_nm` normalized (e.g. `EIS`, `UNIPAY`) |
| `meta.kind` | str | `"journey"` \| `"downstream"` |
| `meta.route` | str | route/destination (e.g. `thirdParty/wrapper/Martech`) |
| `durationMs` | int | call duration in ms |
| `transportOk` | bool | transport-level success (`trns_sts`) |
| `businessOk` | bool | business-level success (decoded from payload) |

Used by the agent's `verify`/baseline logic: p50/p95 duration and error/
business-failure rate for the incident window vs the preceding 30 minutes,
grouped by route (`$dateTrunc` 5s + `$percentile`).

---

## `incidents` — agent-written RCA output

| Field | Type | Meaning |
|---|---|---|
| `incidentKey` | str | stable key, e.g. `route:<srvcId>:<errCd>:<ISO-minute>` |
| `status` | str | `"analyzing"` \| `"complete"` \| `"failed"` |
| `trnsIds` | [str] | correlated transaction ids |
| `sessnTknIds` | [str] | correlated session tokens |
| `firstErrorAt` | Date | earliest error in the incident |
| `analyzedAt` | Date | when analysis completed |
| `durationMs` | int | analysis wall time |
| `errCds` | [str] | error codes observed |
| `journeysInvolved` | [str] | `cmnd_id`s |
| `systemsInvolved` | [str] | `systm_nm`/`srvc_id`s |
| `originComponent` | str | the true root-cause component (NOT the loudest error) |
| `timeline` | [obj] | ordered cross-collection events: `{ts, trnsId, journey, system, srvcId, errCd, businessStatus, transportStatus, decodedErrorChain, durationMs, note}` |
| `metrics` | obj | `{p95BaselineMs, p95IncidentMs, usersAffected}` |
| `rca` | obj | `{rootCause, causalChain:[str], contributingFactors:[str], evidence:[str _id], confidence:0..1, unknowns:[str]}` |
| `blastRadius` | obj | `{journeys:[str], channels:[int], userCount:int}` |
| `recommendations` | [obj] | `{tier:"immediate"\|"fix"\|"prevention", action, ownerSystem, effort:"S"\|"M"\|"L", impact:"H"\|"M"\|"L"}` |
| `recalledIncidents` | [obj] | `{incidentKey, score}` |
| `recalledKb` | [obj] | `{title, score}` |
| `nodeTrace` | [obj] | per-node execution trace (input/output/pipeline/ms) |

---

## `incident_memory` — agent-written distilled learnings (vector-indexed)

`summary_text` is embedded and synced by Atlas **Automated Embedding**
(`voyage-4-lite`); no embedding field is ever written by code.

| Field | Type | Meaning |
|---|---|---|
| `incidentKey` | str | key of the source incident |
| `summary_text` | str | signature + narrative + resolution (vector-indexed) |
| `err_cds` | [str] | error codes in the incident |
| `srvc_ids` | [str] | downstream routes involved |
| `journeys` | [str] | journeys involved |
| `createdAt` | Date | when the memory was written |
| `sourceIncidentKey` | str | provenance link |

Indexes (do not touch): `incident_memory_search` (lexical), `incident_memory_vector`
(`autoEmbed`, query with `query:{text:…}`, never a `queryVector`).

---

## `kb_docs` — seeded knowledge base (vector-indexed)

~15 curated runbook/ownership/known-issue entries, seeded by `python data/seed.py --kb`.
`body` gets the same `autoEmbed` treatment as `incident_memory.summary_text`.

| Field | Type | Meaning |
|---|---|---|
| `title` | str | short title |
| `body` | str | rich prose for semantic recall (vector-indexed) |
| `codes` | [str] | exact error/compliance codes (lexical arm) |
| `tags` | [str] | topical tags |

Indexes (do not touch): `kb_docs_search` (lexical over `body`/`codes`/`tags`/`title`),
`kb_docs_vector` (`autoEmbed` over `body`).

---

## Related collections (not defined here)

`agent_state` (`_id:"resume:<stream>"|"watcher:heartbeat"|"sim:command"`),
`feedback`, `checkpoints`, `checkpoint_writes`, `store` (LangGraph
`MongoDBSaver` / `MongoDBStore`).
