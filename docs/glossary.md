# NOVA 2.0 Field & Code Glossary

This file is rendered into LLM prompts and the UI's hover-help. Keep it precise
and machine-friendly. The `## codes` section below is a flat `CODE — meaning`
list so it can be parsed line-by-line.

## Abbreviated field names

NOVA audit fields use terse, vowel-dropped names. Both status spellings are live
and MUST NOT be unified.

- `trns` — transaction. `trns_id` = transaction id (the primary correlation key,
  one per journey action / API call). `trns_stts` = transaction status on
  `audit_transaction` (**double-t**: `error` | `success`). `trns_sts` =
  transaction/transport status on `audit_service` (**single-t**: `success` |
  `0` (ok) | `-2` (failure)).
- `sessn_tkn` — session token. `sessn_tkn_id` = the user session id; groups many
  `trns_id`s belonging to one user session.
- `cmnd` — command. `cmnd_id` = the journey/feature identifier, pattern
  `domain_module_feature_action` (e.g. `martech_hyper-personalization_offers_fetch`).
- `chnl` — channel. `chnl_id` = `2001` (mobile) | `1001` (web, the `novaweb_`
  request rows). Mirrored as the friendly `channel` field (`mobile` | `web`).
- `crtd` — created. `crtd_by` = writing user (`TransAdtUser` / `ErrorAdtUser` /
  `ServiceAdtUser`); `crtd_on` = write timestamp (may lag or reorder relative to
  event time — order by `strt_time`/`err_time` + `seq`, not `crtd_on`).
- `stts` vs `sts` — both mean *status*; the spelling differs by collection (see
  `trns_stts` vs `trns_sts` above). This drift is authentic and intentional.
- `usr_id` — user id, a 19-digit string (e.g. `1730709013340810605`).
- `usr_rltnshp_no` — customer relationship number (e.g. `85002721166`).
- `usr_typ` — user type (`ETB_CUSTOMER` = Existing-To-Bank customer).
- `msg_id` — source log message id (int).
- `req_no` — request number (hex, or `novaweb_…` on web).
- `clnt_ip_addr` — client IP address.
- `biz_req_input` / `biz_resp_output` — business request/response JSON strings
  (`biz_resp_output` is often **double-encoded** — JSON inside a JSON string).
- `err_cd` / `err_typ` / `err_dscrptn` / `err_dtls` — error code / type
  (`BUSINESS_EXCEPTION` | `TECHNICAL_EXCEPTION`) / human description / detail
  JSON string (keyed by business code, may nest; innermost code is the real
  cause).
- `biz_err_cd_1..5` / `biz_err_cd_1_msg..5_msg` — flattened business error codes
  and messages; unused slots are the literal string `NULL`.
- `srvc_id` — downstream operation id (e.g. `eis_marTech_getInteractOffers`).
- `srvc_rqst` / `srvc_rspn` — downstream request/response JSON strings.
- `systm_nm` — downstream system name; `' UNIPAY'` carries an authentic **leading
  space**, `'EIS'` does not. Normalize on read.
- `api_url` — full downstream URL.
- `rqst_id_sent` / `rqst_id_rcvd` — downstream request ids (`SBIY22…`, `SB41…`).
- `trace_id` — mostly the literal string `NULL`, occasionally a hex trace id;
  **unreliable** — use `trns_id` to join, never `trace_id`.
- `nfrchk` — legacy flag, always the literal string `NULL`.
- `seq` — monotonic integer per `trns_id`, giving stable event ordering.
- `strt_time` / `end_time` — call start/end (UTC). Duration = `end_time −
  strt_time`, computable per call.

## Status semantics (layered — read both axes)

Status fields lie by design; classify every event on **two** axes:

- **Transport status** (did the wire call complete): `trns_stts`
  (`error`/`success`) and `trns_sts` (`success`/`0`/`-2`).
- **Business status** (did the business intent succeed), which lives **inside the
  payload**: UNIPAY `srvc_rspn.reason.responseCode` (`001`/`Failure` +
  `complianceReason`); EIS `srvc_rspn.EIS_RESPONSE.success` / `.status_code`
  (e.g. `success:false`, `status_code:404`).
- A call can be transport-success but business-fail (UNIPAY `BFR003`), or
  `trns_sts 0` while carrying a `404` (THINK360 summary). Parse payloads up to
  **two** levels (double-encoding) before judging.

## err_cd vocabularies

- `BS*` — **business** exception codes. `BS000001` is the generic wrapper; the
  specific code lives inside `err_dtls` / `biz_err_cd_*` (e.g. `BSYHP003`,
  `BSPAPL010`, `BSDML050`). Never treat `BS000001` as the root cause — unwrap it.
- `TE*` — **technical** exception codes, often journey/system-specific
  (`TEEIS009`, `TEY2GSA02`).
- **bare numerics** — legacy technical/transport codes: `5151` (generic service
  execution failure); on `audit_service`, `200` (HTTP-ish ok / no data), `1`
  (internal failure marker), `0` / `-2` (status markers).

## Systems & routes

- `EIS` — Enterprise Integration Services gateway; fronts all surrounding-system
  calls. Route families: `thirdParty/wrapper/Martech` (Martech offers,
  `MARTECH_DWH`), `thirdParty/wrapper/services` (THINK360, `IT_JVP`),
  `misc/microservice` (EIS-native, e.g. CustEnquiry). Shared connection pool.
- `UNIPAY` (`' UNIPAY'`) — BBPS autopay/billpay provider; layered compliance
  statuses.
- `MARTECH_DWH` — Martech audience/offer engine behind EIS.
- `IT_JVP` / `THINK360` — financial-fitness data provider behind EIS; JWT token
  lifecycle (`accessToken` → Bearer token with `expiry`).
- `CBS` — core banking, behind the demand-loan-discharge dependency.
- `IAM` — identity/authentication service behind login (`eis_iam_authenticate` via EIS).
- `UPI switch` — NPCI-style payment switch behind send-money (`unipay_upi_payment_transfer` via UNIPAY).

## codes

Flat `CODE — meaning` list (machine-parseable):

BS000001 — Generic business exception wrapper; the specific business code is nested in err_dtls / biz_err_cd_* and must be unwrapped.
BSYHP003 — Martech: "CIF Is Not Recognized By Martech." The customer's CIF is missing from the Martech audience store (single = benign; cohort spike = Martech CIF desync, often after an audience refresh).
BSPAPL010 — PAPL personal-loan eligibility: "Sorry! This offer is not available to you." Expected customer-specific ineligibility; low background rate is benign noise, not an incident.
BSDML050 — Demand-loan closure outer/customer-facing business failure ("Your Demand Loan closure request has failed. Kindly visit branch..."); wraps an inner code in err_dtls.
BSDML024 — Demand-loan inner code carrying loan_discharge "received improper response"; the real cause — the CBS loan-discharge dependency returned a malformed/improper body (contract violation).
TEEIS009 — EIS technical: "Response Transformation failed." The EIS gateway could not map a downstream vendor's response to the expected schema; signals a downstream brownout/garbled body (long duration, trns_sts -2). Origin is the shared EIS route, not the loud journey error.
TEY2GSA02 — GSA insurance technical exception during request validation/processing "due to unexpected data state"; timeout-shaped — the real cause is the slow insurer validation dependency, not the validation code.
BFR003 — UNIPAY BBPS compliance reason for a business failure (no bill data / biller failure) returned inside a transport-"success" response (responseCode 001).
SIP019 — UNIPAY BBPS complianceRespCd: standing instruction not available (business failure inside transport success).
5151 — Legacy numeric technical code: "Exception occurred while executing the service." Seen on fast-failing PFM calls when a THINK360 token is expired/unavailable, and in single-client poison-retry loops.
001 — UNIPAY responseCode inside srvc_rspn.reason indicating a business Failure (pair with complianceReason such as BFR003).
200 — UNIPAY/HTTP-ish responseCode for a benign OK / "No data found" result.
0 — audit_service transport status marker meaning ok (may still carry a business failure inside the payload, e.g. EIS 404).
-2 — audit_service transport status marker meaning failure (e.g. accompanies TEEIS009).
TEIAM001 — IAM/identity technical failure: "IAM authentication service unavailable." The shared auth dependency behind auth_login_user_authenticate is down (trns_sts -2); users see failed logins (5151 journey errors), but the origin is the IAM route on the EIS gateway.
U68 — NPCI/UPI-style switch timeout: "UPI switch timeout - transaction declined." The unipay_upi_payment_transfer route at UNIPAY timed out; customers see failed UPI payments (5151 journey errors), but the origin is the shared switch route.
