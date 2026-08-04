#!/usr/bin/env python
"""Scenario RCA eval (plan P4 / brief §11 acceptance): does the agent name the
right ORIGIN — never the loudest decoy — for all 8 scenario classes?

This exercises the real graph (correlate → recall → hypothesize → verify → rca)
against canonical, ground-truth-shaped cascades. The agent has NO scenario
knowledge; each injector only writes contract-§1 documents. Grading is by origin
component *family* (ground truth in docs/scenarios-ground-truth.md), plus the
invariant that the origin differs from the loud decoy error code.

Requires a live cluster + Grove (reads .env). Run:  python agent/tests/eval_scenarios.py
Exit 0 iff >= 7/8 correct.
"""
from __future__ import annotations

import datetime as dt
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent"))

from nova_agent.config import settings          # noqa: E402
from nova_agent.db import get_db                 # noqa: E402
from nova_agent.graph.runner import run_incident  # noqa: E402

db = get_db()
EIS = "https://eis-uat.internal/gen6/gateway/misc/thirdParty/wrapper/Martech/services"
UNIPAY = "https://unipay-uat.internal:4443/bbps-autopay-service/pendingBills"
GATEWAY = "https://eis-uat.internal/gen6/gateway"


def _ts(base, i):
    return base + dt.timedelta(milliseconds=250 * i)


def _rid(p):
    return f"178342{random.randint(10**9, 10**10)}{p}"


def _uid(n):
    return str(1730709013340810000 + n)  # contract-valid 19-digit usr_id


def txn(tr, se, uid, cmnd, t0, chnl=2001, stts="error"):
    db[settings.C_TXN].insert_one({"msg_id": random.randint(6_000_000, 9_999_999), "trns_id": tr,
        "sessn_tkn_id": se, "clnt_ip_addr": "10.191.199.66", "req_no": "r", "usr_rltnshp_no": "8500",
        "trns_stts": stts, "strt_time": t0, "end_time": t0 + dt.timedelta(seconds=1), "usr_id": uid,
        "usr_typ": "ETB_CUSTOMER", "cmnd_id": cmnd, "chnl_id": chnl,
        "channel": "web" if chnl == 1001 else "mobile", "biz_req_input": "{}", "biz_resp_output": "{}",
        "crtd_by": "TransAdtUser", "crtd_on": t0, "trace_id": "NULL", "nfrchk": "NULL", "seq": 1})


def err(tr, se, uid, err_cd, t0, dtls="{}", biz1="NULL"):
    db[settings.C_ERR].insert_one({"msg_id": random.randint(6_000_000, 9_999_999), "trns_id": tr,
        "sessn_tkn_id": se, "err_cd": err_cd, "err_typ": "BUSINESS_EXCEPTION" if err_cd.startswith("BS")
        else "TECHNICAL_EXCEPTION", "err_dscrptn": "exc", "err_dtls": dtls, "crtd_by": "ErrorAdtUser",
        "crtd_on": t0, "err_time": t0, "usr_id": uid, "biz_err_cd_1": biz1,
        "biz_err_cd_1_msg": "msg" if biz1 != "NULL" else "NULL",
        "biz_err_cd_2": "NULL", "biz_err_cd_3": "NULL", "biz_err_cd_4": "NULL", "biz_err_cd_5": "NULL",
        "biz_err_cd_2_msg": "NULL", "biz_err_cd_3_msg": "NULL", "biz_err_cd_4_msg": "NULL",
        "biz_err_cd_5_msg": "NULL", "seq": 2})


def svc(tr, se, uid, srvc_id, t0, dur_s=1.0, trns_sts=-2, err_cd="", rspn="{}", url=EIS, systm="EIS"):
    db[settings.C_SVC].insert_one({"msg_id": random.randint(6_000_000, 9_999_999), "trns_id": tr,
        "sessn_tkn_id": se, "trns_sts": trns_sts, "err_cd": err_cd, "err_msg": "m", "usr_id": uid,
        "srvc_rqst": "{}", "srvc_rspn": rspn, "srvc_id": srvc_id, "systm_nm": systm, "api_url": url,
        "rqst_id_sent": "SB", "rqst_id_rcvd": "SB", "crtd_by": "ServiceAdtUser", "crtd_on": t0,
        "strt_time": t0, "end_time": t0 + dt.timedelta(seconds=dur_s), "seq": 1})


def metrics(route, service, system, now, inc_ms, base_ms=400):
    rows = []
    for k in range(40):
        tb = now - dt.timedelta(minutes=30) + dt.timedelta(seconds=25 * k)
        if tb < now - dt.timedelta(seconds=90):
            rows.append({"ts": tb, "meta": {"service": service, "system": system, "kind": "downstream",
                         "route": route}, "durationMs": random.randint(base_ms - 100, base_ms + 100),
                         "transportOk": True, "businessOk": True})
    for k in range(8):
        rows.append({"ts": now - dt.timedelta(seconds=60) + dt.timedelta(seconds=5 * k),
                     "meta": {"service": service, "system": system, "kind": "downstream", "route": route},
                     "durationMs": inc_ms, "transportOk": False, "businessOk": False})
    db[settings.C_METRICS].insert_many(rows)


# ------------------------------------------------------------------ injectors
def inj_brownout(now):
    trns, sess = [], []
    metrics("wrapper/Martech/services", "eis_marTech_getInteractOffers", "EIS", now, 10100)
    for i in range(3):
        t = _ts(now, i); tr, se, uid = _rid(f"b{i}"), _rid(f"s{i}"), _uid(i)
        txn(tr, se, uid, "martech_hyper-personalization_offers_fetch", t)
        svc(tr, se, uid, "eis_marTech_getInteractOffers", t, 10.1, -2, "TEEIS009",
            '{"ERROR_CODE":"TEEIS009","EIS_RESPONSE":{"status_code":500,"success":false}}')
        err(tr, se, uid, "BS000001", t + dt.timedelta(seconds=10),
            '{"BSYHP003":{"message":"CIF Is Not Recognized By Martech."}}', "BSYHP003")
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_cif_desync(now):
    trns, sess = [], []
    # SUCCESS precursor ops txn ~45s earlier
    txn(_rid("ops"), _rid("sops"), _uid(99), "ops_martech_audience_refresh_execute",
        now - dt.timedelta(seconds=45), stts="success")
    for i in range(3):
        t = _ts(now, i); tr, se, uid = _rid(f"c{i}"), _rid(f"s{i}"), _uid(10+i)
        txn(tr, se, uid, "martech_hyper-personalization_offers_fetch", t)
        # normal latency, business fail (BSYHP003), NO TEEIS009
        svc(tr, se, uid, "eis_marTech_getInteractOffers", t, 0.4, 0, "",
            '{"ERROR_CODE":"BSYHP003","EIS_RESPONSE":{"status_code":200,"success":false}}')
        err(tr, se, uid, "BSYHP003", t, '{"BSYHP003":{"message":"CIF Is Not Recognized By Martech."}}', "BSYHP003")
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_think360(now):
    trns, sess = [], []
    for i in range(3):
        t = _ts(now, i); tr, se, uid = _rid(f"k{i}"), _rid(f"s{i}"), _uid(20+i)
        txn(tr, se, uid, "pfm_financial-fitness_customer_kyc_fetch", t)
        # credential call barely registers, fails first (fast)
        svc(tr, se, uid, "eis_financialfitness_accessToken", t, 0.005, -2, "5151",
            '{"ERROR_CODE":"5151","EIS_RESPONSE":{"status_code":401,"success":false}}',
            url="https://eis-uat.internal/gen6/gateway/misc/thirdParty/wrapper/Think360/token", systm="EIS")
        svc(tr, se, uid, "eis_financialfitness_summary", t + dt.timedelta(milliseconds=50), 0.05, 0, "",
            '{"ERROR_CODE":"","EIS_RESPONSE":{"status_code":404,"success":false,"message":"Data Not Found"}}',
            url="https://eis-uat.internal/gen6/gateway/misc/thirdParty/wrapper/Think360/summary")
        err(tr, se, uid, "5151", t + dt.timedelta(milliseconds=10))
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_unipay(now):
    trns, sess = [], []
    for i in range(4):
        t = _ts(now, i); tr, se, uid = _rid(f"u{i}"), _rid(f"s{i}"), _uid(30+i)
        txn(tr, se, uid, "billpay_autopay_pendingbills_fetch", t, stts="success")
        # transport success, business failure via reason.responseReason (no audit_error at all)
        svc(tr, se, uid, "unipay_payment_billpay_autopay_pendingbills", t, 0.3, "success", "200",
            '{"head":{},"reason":{"responseCode":"001","responseReason":"Failure","complianceReason":"BFR003"}}',
            url=UNIPAY, systm=" UNIPAY")
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_gsa(now):
    trns, sess = [], []
    metrics("gsa/validate/checks", "gi_gsa_purchase_validate_checks", "EIS", now, 15100)
    for i in range(3):
        t = _ts(now, i); tr, se, uid = _rid(f"g{i}"), _rid(f"s{i}"), _uid(40+i)
        txn(tr, se, uid, "gi_gsa_purchase_validate_checks", t, chnl=1001)
        svc(tr, se, uid, "gi_gsa_purchase_validate_checks", t, 15.1, -2, "TEY2GSA02",
            '{"ERROR_CODE":"TEY2GSA02","EIS_RESPONSE":{"status_code":504,"success":false}}',
            url="https://eis-uat.internal/gen6/gateway/misc/gsa/validate/checks")
        err(tr, se, uid, "TEY2GSA02", t + dt.timedelta(seconds=15))
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_demand_loan(now):
    trns, sess = [], []
    dtls = ('{"BSDML050":{"data":{"BSDML024":{"data":{"loan_discharge":"received improper response"},'
            '"message":"technical issue"}},"message":"Your Demand Loan closure request has failed."}}')
    for i in range(2):
        t = _ts(now, i); tr, se, uid = _rid(f"d{i}"), _rid(f"s{i}"), _uid(50+i)
        txn(tr, se, uid, "lending_demand_demand-loan-closure_manage", t)
        svc(tr, se, uid, "cbs_loan_discharge_manage", t, 11.7, -2, "BSDML024",
            '{"ERROR_CODE":"BSDML024","EIS_RESPONSE":{"status_code":502,"success":false}}',
            url="https://eis-uat.internal/gen6/gateway/misc/cbs/loan/discharge", systm="EIS")
        err(tr, se, uid, "BSDML050", t + dt.timedelta(seconds=11), dtls, "BSDML050")
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_poison(now):
    trns, sess = [], []
    uid, se = _uid(0), _rid("sp")   # ONE user, ONE session
    for i in range(6):
        t = _ts(now, i); tr = _rid(f"p{i}")
        txn(tr, se, uid, "loan_personal_papl_getEligibleLoanDetails", t)
        err(tr, se, uid, "5151", t)
        trns.append(tr)
    sess.append(se)
    return trns, sess


def inj_gateway(now):
    trns, sess = [], []
    routes = ["eis_marTech_getInteractOffers", "eis_financialfitness_accessToken",
              "eis_financialfitness_summary", "eis_etb_customerprofile_querycustprofile",
              "eis_cc_branchportal_account_cifAssociatedAccount"]
    journeys = ["martech_hyper-personalization_offers_fetch", "pfm_financial-fitness_customer_kyc_fetch",
                "pfm_financial-fitness_summary_fetch", "home_dashboard_cards_getAllCCAccountSummary",
                "pfm_financial-fitness_consent_fetch"]
    for i, (r, j) in enumerate(zip(routes, journeys)):
        t = _ts(now, i); tr, se, uid = _rid(f"x{i}"), _rid(f"s{i}"), _uid(60+i)
        txn(tr, se, uid, j, t)
        svc(tr, se, uid, r, t, 0.02, -2, "TEEIS009",
            '{"ERROR_CODE":"TEEIS009","EIS_RESPONSE":{"status_code":503,"success":false}}', url=GATEWAY)
        err(tr, se, uid, "BS000001", t, biz1="BSYHP003")
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_login(now):
    trns, sess = [], []
    metrics("iam/authenticate", "eis_iam_authenticate", "EIS", now, 4100, base_ms=200)
    for i in range(3):
        t = _ts(now, i); tr, se, uid = _rid(f"l{i}"), _rid(f"s{i}"), _uid(70 + i)
        txn(tr, se, uid, "auth_login_user_authenticate", t)
        svc(tr, se, uid, "eis_iam_authenticate", t, 4.1, -2, "TEIAM001",
            '{"ERROR_CODE":"TEIAM001","EIS_RESPONSE":{"status_code":503,"success":false}}',
            url="https://eis-uat.internal/gen6/gateway/misc/iam/authenticate")
        err(tr, se, uid, "5151", t + dt.timedelta(seconds=4))
        trns.append(tr); sess.append(se)
    return trns, sess


def inj_upi(now):
    trns, sess = [], []
    metrics("upi-switch/payment", "unipay_upi_payment_transfer", "UNIPAY", now, 8100, base_ms=240)
    for i in range(3):
        t = _ts(now, i); tr, se, uid = _rid(f"v{i}"), _rid(f"s{i}"), _uid(80 + i)
        txn(tr, se, uid, "upi_payment_send_money", t)
        svc(tr, se, uid, "unipay_upi_payment_transfer", t, 8.1, "-2", "U68", "{}",
            url="https://unipay-uat.internal:4443/upi-switch/payment/transfer", systm=" UNIPAY")
        err(tr, se, uid, "5151", t + dt.timedelta(seconds=8))
        trns.append(tr); sess.append(se)
    return trns, sess


SCENARIOS = {
    "login-failures": (inj_login, ["iam", "authenticate"], "5151"),
    "upi-payment-failures": (inj_upi, ["upi", "transfer", "switch"], "5151"),
    "eis-martech-brownout": (inj_brownout, ["martech", "interactoffers"], "BS000001"),
    "martech-cif-desync": (inj_cif_desync, ["martech", "audience", "refresh", "interactoffers"], "BSYHP003"),
    "think360-token-expiry": (inj_think360, ["accesstoken", "financialfitness", "token", "think360"], "5151"),
    "unipay-bbps-brownout": (inj_unipay, ["unipay", "billpay", "autopay", "pendingbills"], None),
    "gsa-validation-hang": (inj_gsa, ["gsa", "validate", "purchase", "insurer"], "TEY2GSA02"),
    "demand-loan-improper-response": (inj_demand_loan, ["loan", "discharge", "cbs", "bsdml024", "demand"], "BSDML050"),
    "poison-retry-loop": (inj_poison, ["papl", "5151", "loan_personal", "client"], None),
    "eis-gateway-pool-exhaustion": (inj_gateway, ["eis_", "gateway"], "BS000001"),
}


def _clear():
    for c in (settings.C_TXN, settings.C_ERR, settings.C_SVC, settings.C_METRICS,
              settings.C_INCIDENTS, settings.C_MEMORY, settings.C_STORE, settings.C_STATE,
              settings.C_CHECKPOINTS, settings.C_CHECKPOINT_WRITES):
        db[c].delete_many({})


def run() -> int:
    results = []
    for name, (inject, expect, decoy) in SCENARIOS.items():
        _clear()
        now = dt.datetime.now(dt.timezone.utc)
        trns, sess = inject(now)
        key = f"eval-{name}:{int(time.time()*1000)}"
        run_incident({"incident_key": key, "trns_ids": trns, "sessn_tkn_ids": sess, "signature": name})
        doc = db[settings.C_INCIDENTS].find_one({"incidentKey": key}) or {}
        origin = (doc.get("originComponent") or "").lower()
        root = (doc.get("rca", {}) or {}).get("rootCause", "").lower()
        hay = origin + " " + root
        hit = any(tok.lower() in hay for tok in expect)
        # origin invariant: the origin must not merely be the loud decoy error code
        not_decoy = True if decoy is None else (decoy.lower() not in origin)
        ok = hit and not_decoy
        results.append((name, ok, doc.get("originComponent"), (doc.get("rca", {}) or {}).get("confidence")))
        print(f"[{'PASS' if ok else 'FAIL'}] {name:32s} origin={doc.get('originComponent')} "
              f"conf={(doc.get('rca',{}) or {}).get('confidence')}")

    passed = sum(1 for _, ok, *_ in results if ok)
    print(f"\n{passed}/{len(SCENARIOS)} scenarios correct (origin family matched, ≠ loud decoy)")
    return 0 if passed >= len(SCENARIOS) - 1 else 1


if __name__ == "__main__":
    sys.exit(run())
