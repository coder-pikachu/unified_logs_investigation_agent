# Scenario Ground Truth (eval oracle — the agent NEVER reads this)

The RCA agent has **no** scenario-specific logic and never sees this file. It is
the human/eval reference for grading each of the 8 scenarios against §11
verification. In **every** scenario the component that throws the *loudest*
error is NOT the origin — the whole point is cross-collection correlation
(claim #5).

For each scenario:
- **Effects** — the generic effect kinds fired (contract §6); no scenario name
  ever appears in emitted documents.
- **Origin component** — what the RCA `originComponent` / `rca.rootCause` MUST
  name.
- **Loudest (decoy)** — the noisy symptom a naive log reader would blame.
- **Causal chain** — origin → symptom.
- **Blast radius** — journeys / channels / users expected.
- **Proving checks** — the verify-node aggregations that discriminate the origin
  from the decoy.

---

## 1. `eis-martech-brownout`

- **Effects:** `route_latency{srvcId: eis_marTech_getInteractOffers, targetMs≈10000, rampMs}` + `route_error_rate{srvcId: eis_marTech_getInteractOffers, errCd: TEEIS009, errMsg: "Response Transformation failed.", transStatus: -2, rate}` across multiple sessions.
- **Origin component:** the shared **EIS `thirdParty/wrapper/Martech` route** (downstream `eis_marTech_getInteractOffers` / `MARTECH_DWH`). A single downstream route is degraded.
- **Loudest (decoy):** journey-side `martech_hyper-personalization_offers_fetch` failing with `BS000001` / `BSYHP003` on many dashboards — many loud journey errors.
- **Causal chain:** Martech offer engine slows → EIS response transformation fails (`TEEIS009`, ~10s duration, `trns_sts -2`) → offers-fetch journey returns generic `BS000001/BSYHP003` for every user who loaded a dashboard.
- **Blast radius:** journeys `[martech_hyper-personalization_offers_fetch]` (one journey), channel `[2001]` (mobile), many users/sessions.
- **Proving checks:** (a) **incidence** — `distinct usr_id/sessn_tkn_id` with `TEEIS009` on `eis_marTech_getInteractOffers` in the window ≫ 1 (systemic, not one client). (b) **baseline** — p95 duration for that `srvc_id` this window (~10s) vs 30-min baseline (~300–600ms) → blowout. (c) the loud `BS000001`s all share the single failing `srvc_id`. Origin ≠ the journey error.

## 2. `martech-cif-desync`

- **Effects:** `ops_txn{cmndId: ops_martech_audience_refresh_execute}` (a **success** transaction) at T−45s, then `business_failure_rate{cmndId|srvcId: martech offers, complianceCode: BSYHP003, rate}` for a cohort.
- **Origin component:** the **Martech audience refresh ops job** (`ops_martech_audience_refresh_execute`) — a *non-error* precursor that desynced/dropped CIFs from the Martech audience store.
- **Loudest (decoy):** `BSYHP003 "CIF Is Not Recognized By Martech."` business exceptions spiking on offers-fetch for a cohort.
- **Causal chain:** audience refresh runs successfully (logged as `success`, no error doc) → Martech audience store loses/expires the cohort's CIFs → minutes later offers-fetch returns `BSYHP003` for exactly that cohort.
- **Blast radius:** journeys `[martech_hyper-personalization_offers_fetch]`, channel `[2001]`, a bounded **cohort** of users (not all).
- **Proving checks:** (a) **precursor** — an ops/config transaction on the Martech component in the prior ~10 min (the refresh) exists and is `success`. (b) `BSYHP003` here rides on **normal** EIS route latency and there is **no** `TEEIS009` — distinguishes from eis-martech-brownout. (c) affected users form a cohort tied to the refresh. Origin is the green success doc, not the red business errors.

## 3. `think360-token-expiry`

- **Effects:** `token_expiry{srvcId: eis_financialfitness_accessToken}` → accessToken renewal fails / JWT `expiry` passes; dependent PFM calls fast-fail with `route_error_rate{errCd: 5151}` and/or 404-inside-success on `eis_financialfitness_summary`.
- **Origin component:** the shared **THINK360 credential/token dependency** (`eis_financialfitness_accessToken`, EIS `IT_JVP`). One credential fans out.
- **Loudest (decoy):** many PFM journeys (`pfm_financial-fitness_customer_kyc_fetch`, `_summary_fetch`) failing simultaneously with legacy `5151` (and 404 buried inside `trns_sts 0`).
- **Causal chain:** token renewal fails / JWT `expiry` has passed → every PFM call using that Bearer token fails almost instantly (single-digit ms) with `5151`, or gets a 404 `Data Not Found` inside a transport-`0` EIS response.
- **Blast radius:** journeys `[pfm_financial-fitness_customer_kyc_fetch, pfm_financial-fitness_summary_fetch]`, channel `[2001]`, many users across sessions at once.
- **Proving checks:** (a) the `accessToken` call itself **barely registers** (few/one events) yet correlates in time with a broad PFM failure fan-out — origin is the low-volume credential call. (b) **fast-fail signature** — dependent failures have tiny durations (ms), unlike a latency brownout. (c) decode the EIS `summary` payload to expose `success:false / status_code 404` behind `trns_sts 0`. (d) JWT `expiry` epoch < event time.

## 4. `unipay-bbps-brownout`

- **Effects:** `business_failure_rate{srvcId: unipay_payment_billpay_autopay_pendingbills, complianceCode: BFR003, rate}` climbing over ~3 min while `trns_sts` stays `success` (transport ok).
- **Origin component:** the **UNIPAY BBPS autopay backend** (`unipay_payment_billpay_autopay_*`, systm_nm `' UNIPAY'`) — a business-layer brownout.
- **Loudest (decoy):** billpay/autopay journey "failures" — but **no status field ever turns red**; `trns_sts` reads `success` throughout.
- **Causal chain:** UNIPAY biller backend degrades → rising ratio of `responseCode 001 / responseReason Failure / complianceReason BFR003` inside otherwise transport-successful responses → billpay journey experience fails for users.
- **Blast radius:** journeys `[billpay_autopay_pendingbills_fetch, billpay_autopay_favouritebillers_query]`, channel `[2001]`, users growing over the ~3-min ramp.
- **Proving checks:** (a) **layered-status decode** — classify events as transport-ok / business-fail by parsing `srvc_rspn.reason` (never trust `trns_sts`). (b) **time-series trend** — `businessOk=false` rate for the UNIPAY route climbing across 5s buckets vs baseline, while `transportOk` stays true. This is the "no red status" trap.

## 5. `gsa-validation-hang`

- **Effects:** `route_latency{srvcId: gi_gsa_purchase_validate_checks (journey) / its insurer dependency, targetMs≈15000, rampMs}` then `route_error_rate{errCd: TEY2GSA02, transStatus, rate}` after the timeout.
- **Origin component:** the **external insurer validation dependency** behind GSA purchase validation — its latency, not the journey's validation code.
- **Loudest (decoy):** `gi_gsa_purchase_validate_checks` throwing `TEY2GSA02` ("...request validation... unexpected data state"), which reads like a validation-logic bug.
- **Causal chain:** insurer dependency slows → journey p95 climbs to ~15s → request times out → journey emits `TEY2GSA02` technical exception.
- **Blast radius:** journeys `[gi_gsa_purchase_validate_checks]`, channel `[1001]` (**web**), users hitting GSA purchase in the window.
- **Proving checks:** (a) **latency-shaped** — duration (`end_time − strt_time`) ≈15s precedes the error; p95 vs baseline blowout on the validation route. (b) the `TEY2GSA02` fires **after** the timeout, not immediately — timeout signature, so the origin is the dependency latency, not the code. Note web channel (`chnl_id 1001`).

## 6. `demand-loan-improper-response`

- **Effects:** `route_error_rate{...}` producing nested `err_dtls` `{"BSDML050":{...{"BSDML024":{... "loan_discharge":"received improper response"}}}}` on `lending_demand_demand-loan-closure_manage` (~11.7s duration).
- **Origin component:** the **CBS loan-discharge dependency** returning a **malformed/improper response body** — a contract violation named by the innermost code `BSDML024`.
- **Loudest (decoy):** the outer, customer-facing `BSDML050` ("...request has failed. Kindly visit branch...") — the public wrapper.
- **Causal chain:** loan-discharge dependency returns an improper body → inner `BSDML024 "received improper response"` → wrapped as outer `BSDML050` → journey fails.
- **Blast radius:** journeys `[lending_demand_demand-loan-closure_manage]`, channel `[2001]`, the affected borrowers (can be narrow).
- **Proving checks:** (a) **unwrap `err_dtls`** to the innermost code (`BSDML024`) and quote `"received improper response"` — name the innermost cause AND the malformed-contract nature. (b) RCA must NOT stop at `BSDML050`. Evidence cites the specific `audit_error._id`.

## 7. `poison-retry-loop`

- **Effects:** `client_replay{cmndId, count, errCd: 5151}` — one client app replays a malformed `biz_req_input`, producing identical technical exceptions for **one** `usr_id`/`sessn_tkn_id`.
- **Origin component:** a **single misbehaving client app / session** replaying a malformed request — NOT a downstream system.
- **Loudest (decoy):** a high **raw count** of identical `5151` technical exceptions that superficially looks like a systemic outage.
- **Causal chain:** one client repeatedly sends the same malformed `biz_req_input` → identical `5151` exceptions repeat for that single user/session.
- **Blast radius:** **one** `usr_id` / one `sessn_tkn_id`; one journey; channel of that client. Radius is intentionally tiny despite the loud count.
- **Proving checks:** (a) **incidence** — `distinct usr_id` and `distinct sessn_tkn_id` carrying the `5151` signature == 1 (contrast with think360-token-expiry / gateway exhaustion where it is many). (b) identical/repeated `biz_req_input`. This is the "loud but not systemic" trap — the discriminator is incidence, not error count.

## 8. `eis-gateway-pool-exhaustion`

- **Effects:** connection-failure `route_error_rate` fired across **all** `eis_*` routes at once (`eis_marTech_getInteractOffers`, `eis_financialfitness_accessToken`, `eis_financialfitness_summary`, `eis_etb_customerprofile_querycustprofile`, `eis_cc_branchportal_account_cifAssociatedAccount`), often with `TEEIS009`/`5151` and connection errors to the shared gateway host.
- **Origin component:** the **shared EIS gateway host / connection pool** — a single shared resource, widest blast radius.
- **Loudest (decoy):** per-journey business exceptions (`BS000001`, `BSYHP003`, and others) on many *different* journeys simultaneously — looks like many unrelated failures.
- **Causal chain:** EIS gateway connection pool exhausts → new connections to the gateway host fail for **every** EIS-backed route at once → every EIS-backed journey (offers, PFM, customer profile, CC summary) degrades together.
- **Blast radius:** **all** EIS-backed journeys (`martech_…offers_fetch`, `pfm_financial-fitness_*`, `home_dashboard_cards_getAllCCAccountSummary`, customer-profile), channels `[2001, 1001]`, the widest user population.
- **Proving checks:** (a) **breadth** — count `distinct srvc_id` (and `systm_nm=EIS` routes) failing in the same window ≫ 1 → many routes at once ⇒ gateway/pool, not one vendor (contrast eis-martech-brownout, where exactly one `srvc_id` fails). (b) all failing routes share the same gateway host in `api_url`. (c) simultaneity across routes in the timeline. Origin is the shared gateway, never any single journey's loudest business error.

## 9. `login-failures` — "User can't log in"

- **Effects:** `route_latency{srvcId: eis_iam_authenticate, targetMs≈4000}` + `route_error_rate{srvcId: eis_iam_authenticate, errCd: TEIAM001, transStatus: -2, rate 0.8}`.
- **Origin component:** the shared **IAM/identity route** (`eis_iam_authenticate`, EIS gateway). Technical fault.
- **Loudest (decoy):** a wall of failed logins — `5151` technical exceptions on `auth_login_user_authenticate` across many users. Reads like "the app is broken".
- **Causal chain:** IAM service degrades → every login's auth call fails (`TEIAM001`, `trns_sts -2`) → each user's login journey errors with `5151`.
- **Blast radius:** journey `[auth_login_user_authenticate]`, channel `[2001]`, every user who tries to log in.
- **Proving checks:** (a) incidence — distinct `usr_id` with the signature ≫ 1; (b) baseline — auth route p95 ~180ms → ~4s; (c) all failures share the single `eis_iam_authenticate` route. Origin ≠ the loud journey errors.

## 10. `upi-payment-failures` — "UPI payments failing"

- **Effects:** `route_latency{srvcId: unipay_upi_payment_transfer, targetMs≈8000}` + `route_error_rate{errCd: U68 (NPCI-style timeout), transStatus: -2, rate 0.75}`.
- **Origin component:** the **UPI switch route at UNIPAY** (`unipay_upi_payment_transfer`). Technical fault.
- **Loudest (decoy):** many customers' failed payments — `5151` journey errors on `upi_payment_send_money` — reads like a wallet/app bug.
- **Causal chain:** UPI switch times out (`U68`) → transfers decline at the switch → each send-money journey errors with `5151`.
- **Blast radius:** journey `[upi_payment_send_money]`, channel `[2001]`, every paying user in the window.
- **Proving checks:** (a) incidence ≫ 1 user; (b) baseline — switch p95 ~240ms → ~8s; (c) one shared switch route behind all failures. Origin ≠ the loud journey errors.
