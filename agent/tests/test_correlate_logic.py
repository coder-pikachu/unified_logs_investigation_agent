"""Unit tests for the deterministic correlation core — the RCA credibility layer.
Each test defends a contract that a specific demo scenario depends on
(layered-status decode, nested err_dtls unwrap, route derivation). Pure Python,
no MongoDB, no Grove.
"""
from nova_agent.graph import nodes


# ---------------------------------------------------------------- double-encode
def test_loads2_plain_json():
    assert nodes._loads2('{"a": 1}') == {"a": 1}


def test_loads2_double_encoded():
    # biz_resp_output / srvc_rspn are frequently JSON-inside-JSON (contract §2.3)
    inner = '{"navigateToNextPage": false}'
    outer = f'{{"response": {inner!r}}}'  # a JSON string whose value is a JSON string
    # build the real double-encoded shape: {"response": "{\"navigateToNextPage\":false}"}
    import json
    doc = json.dumps({"response": json.dumps({"navigateToNextPage": False})})
    got = nodes._loads2(doc)
    assert got["response"] == json.dumps({"navigateToNextPage": False})


def test_loads2_non_json_passthrough():
    assert nodes._loads2("NULL") == "NULL"
    assert nodes._loads2(None) is None


# ---------------------------------------------------------------- nested err_dtls
def test_unwrap_err_dtls_reaches_innermost_cause():
    # demand-loan-improper-response: BSDML050 wraps BSDML024 (the real cause)
    dtls = ('{"BSDML050":{"data":{"BSDML024":{"data":{"loan_discharge":'
            '"received improper response"},"message":"technical issue"}},'
            '"message":"Your Demand Loan closure request has failed."}}')
    chain = nodes._unwrap_err_dtls(dtls)
    codes = [c["code"] for c in chain]
    assert codes == ["BSDML050", "BSDML024"], f"must unwrap to innermost, got {codes}"
    assert chain[-1]["message"] == "technical issue"


def test_unwrap_err_dtls_single_level():
    chain = nodes._unwrap_err_dtls('{"BSYHP003":{"message":"CIF Is Not Recognized By Martech."}}')
    assert chain and chain[0]["code"] == "BSYHP003"


def test_unwrap_err_dtls_garbage_is_safe():
    assert nodes._unwrap_err_dtls("NULL") == []
    assert nodes._unwrap_err_dtls(None) == []


# ---------------------------------------------------------------- layered status
def test_svc_business_unipay_failure_inside_success():
    # unipay-bbps-brownout: transport ok, business FAIL via reason.responseReason
    rspn = '{"head":{},"reason":{"responseCode":"001","responseReason":"Failure","complianceReason":"BFR003"}}'
    ok, code = nodes._svc_business(rspn)
    assert ok is False
    assert code == "BFR003"


def test_svc_business_eis_404_inside_success():
    # think360: 404 buried inside a transport-ok EIS response
    rspn = '{"ERROR_CODE":"","EIS_RESPONSE":{"status_code":404,"success":false,"message":"Data Not Found"}}'
    ok, code = nodes._svc_business(rspn)
    assert ok is False
    assert code in (404, "404")


def test_svc_business_eis_error_code_field():
    rspn = '{"ERROR_CODE":"TEEIS009","EIS_RESPONSE":{"status_code":500,"success":false}}'
    ok, code = nodes._svc_business(rspn)
    assert ok is False


def test_svc_business_clean_success():
    ok, code = nodes._svc_business('{"ERROR_CODE":"","EIS_RESPONSE":{"status_code":200,"success":true}}')
    assert ok is True and code is None


def test_svc_business_null_literal_not_a_failure():
    ok, code = nodes._svc_business('{"ERROR_CODE":"NULL","EIS_RESPONSE":{"success":true}}')
    assert ok is True


# ---------------------------------------------------------------- transport
def test_transport_ok_mixed_vocabulary():
    assert nodes._transport_ok("success") is True
    assert nodes._transport_ok("0") is True       # 0 == ok in audit_service
    assert nodes._transport_ok(0) is True
    assert nodes._transport_ok("-2") is False      # -2 == failure (string)
    assert nodes._transport_ok(-2) is False        # novasim emits int -2
    assert nodes._transport_ok("error") is False


# ---------------------------------------------------------------- route derivation
def test_route_of_extracts_wrapper_route():
    svc = {"api_url": "https://eis-uat.internal/gen6/gateway/misc/thirdParty/wrapper/Martech/services",
           "srvc_id": "eis_marTech_getInteractOffers"}
    assert nodes._route_of(svc) == "wrapper/Martech/services"


def test_route_of_falls_back_to_srvc_id():
    assert nodes._route_of({"api_url": "", "srvc_id": "eis_x"}) == "eis_x"


# ---------------------------------------------------------------- normalize
def test_norm_strips_unipay_leading_space():
    assert nodes._norm(" UNIPAY") == "UNIPAY"
    assert nodes._norm(None) == ""


# ---------------------------------------------------------------- source app
def test_source_app_maps_writers_to_services():
    # journey tier writes audit_transaction / audit_error
    assert nodes._source_app({"collection": "audit_transaction"}) == "NOVA App"
    assert nodes._source_app({"collection": "audit_error"}) == "NOVA App"
    # downstream connectors write audit_service, distinguished by systm_nm
    assert nodes._source_app({"collection": "audit_service", "system": "EIS"}) == "EIS Gateway"
    assert nodes._source_app({"collection": "audit_service", "system": " UNIPAY"}) == "UNIPAY BBPS"
    assert nodes._source_app({"collection": "audit_service", "system": "CBS"}) == "Cbs"


# ---------------------------------------------------------------- correlation block
def test_build_correlation_aggregates_services_and_joins():
    tl = [
        {"collection": "audit_transaction", "sourceApp": "NOVA App", "trnsId": "t1"},
        {"collection": "audit_transaction", "sourceApp": "NOVA App", "trnsId": "t2"},
        {"collection": "audit_error", "sourceApp": "NOVA App", "trnsId": "t1"},
        {"collection": "audit_service", "sourceApp": "EIS Gateway", "trnsId": "t1"},
        {"collection": "audit_service", "sourceApp": "EIS Gateway", "trnsId": "t2"},
        {"collection": "audit_service", "sourceApp": "UNIPAY BBPS", "trnsId": "t2"},
    ]
    c = nodes.build_correlation(tl)
    assert c["totalDocs"] == 6
    assert c["joinKeys"]["trns_id"] == 2                      # distinct t1, t2
    assert c["collections"] == {"audit_transaction": 2, "audit_error": 1, "audit_service": 3}
    by_name = {s["name"]: s for s in c["services"]}
    assert by_name["NOVA App"]["docs"] == 3
    assert sorted(by_name["NOVA App"]["collections"]) == ["audit_error", "audit_transaction"]
    assert by_name["EIS Gateway"]["docs"] == 2
    assert by_name["UNIPAY BBPS"]["collections"] == ["audit_service"]
    # sorted by doc count desc — the loudest writer first
    assert c["services"][0]["name"] == "NOVA App"
