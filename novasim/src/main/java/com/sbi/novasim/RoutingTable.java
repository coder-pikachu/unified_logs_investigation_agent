package com.sbi.novasim;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The NOVA 2.0 journey mesh: the 15 journeys (cmnd_ids) with their channel and
 * downstream routes, plus verbatim payload-envelope builders per system.
 *
 * <p>Downstream hosts are lookalikes only ({@code eis-uat.internal},
 * {@code unipay-uat.internal:4443}) — never a real sbi.co.in host.
 */
public final class RoutingTable {

    /**
     * A journey/feature.
     *
     * @param cmndId     cmnd_id
     * @param chnlId     2001 mobile / 1001 web
     * @param channel    "mobile" / "web"
     * @param downstream ordered downstream srvc_ids
     * @param ops        true for ops/audit journeys (always emitted as success)
     * @param weight     relative selection weight for background traffic
     */
    public record Journey(String cmndId, int chnlId, String channel, List<String> downstream,
                          boolean ops, double weight) {
    }

    private static final Map<String, Route> ROUTES = new LinkedHashMap<>();
    private static final Map<String, Journey> JOURNEYS = new LinkedHashMap<>();

    static {
        route("eis_marTech_getInteractOffers", Route.EIS, "EIS",
                "https://eis-uat.internal/gen6/gateway/misc/thirdParty/wrapper/Martech/services",
                "thirdParty/wrapper/Martech", 320, 0.45, "EIS_MARTECH");
        route("eis_financialfitness_accessToken", Route.EIS, "EIS",
                "https://eis-uat.internal/gen6/gateway/misc/CCSID/thirdParty/wrapper/services",
                "CCSID/thirdParty/wrapper", 120, 0.35, "EIS_TOKEN");
        route("eis_financialfitness_summary", Route.EIS, "EIS",
                "https://eis-uat.internal/gen6/gateway/misc/CCSID/thirdParty/wrapper/services",
                "CCSID/thirdParty/wrapper", 260, 0.4, "EIS_THINK360");
        route("eis_etb_customerprofile_querycustprofile", Route.EIS, "EIS",
                "https://eis-uat.internal/gen6/gateway/misc/microservice/CustEnquiry",
                "microservice/CustEnquiry", 280, 0.4, "EIS_CUSTPROFILE");
        route("eis_cc_branchportal_account_cifAssociatedAccount", Route.EIS, "EIS",
                "https://eis-uat.internal/gen6/gateway/misc/Y2/thirdParty/microService/cifEnquiry",
                "Y2/thirdParty/microService/cifEnquiry", 540, 0.4, "EIS_CIF");
        route("unipay_payment_billpay_autopay_pendingbills", Route.UNIPAY, "UNIPAY",
                "https://unipay-uat.internal:4443/bbps-autopay-service/upcomingBills",
                "bbps-autopay-service", 150, 0.35, "UNIPAY");
        route("unipay_payment_billpay_autopay_query_favouritebillers", Route.UNIPAY, "UNIPAY",
                "https://unipay-uat.internal:4443/bbps-autopay-service/viewNotification",
                "bbps-autopay-service", 160, 0.35, "UNIPAY");
        route("unipay_payment_billpay_autopay_get_active_activebillshistory", Route.UNIPAY, "UNIPAY",
                "https://unipay-uat.internal:4443/v2/txnStatus",
                "v2/txnStatus", 210, 0.4, "UNIPAY");
        route("eis_iam_authenticate", Route.EIS, "EIS",
                "https://eis-uat.internal/gen6/gateway/misc/iam/authenticate",
                "iam/authenticate", 180, 0.35, "EIS_IAM");
        route("unipay_upi_payment_transfer", Route.UNIPAY, "UNIPAY",
                "https://unipay-uat.internal:4443/upi-switch/payment/transfer",
                "upi-switch/payment", 240, 0.4, "UNIPAY");

        journey("auth_login_user_authenticate", 2001, "mobile",
                List.of("eis_iam_authenticate"), false, 10);
        journey("upi_payment_send_money", 2001, "mobile",
                List.of("unipay_upi_payment_transfer"), false, 9);
        journey("martech_hyper-personalization_offers_fetch", 2001, "mobile",
                List.of("eis_marTech_getInteractOffers"), false, 12);
        journey("pfm_financial-fitness_customer_kyc_fetch", 2001, "mobile",
                List.of("eis_financialfitness_accessToken", "eis_etb_customerprofile_querycustprofile"),
                false, 8);
        journey("pfm_financial-fitness_consent_fetch", 2001, "mobile",
                List.of("eis_financialfitness_accessToken"), false, 6);
        journey("pfm_financial-fitness_summary_fetch", 2001, "mobile",
                List.of("eis_financialfitness_accessToken", "eis_financialfitness_summary"), false, 7);
        journey("lending_demand_demand-loan-closure_manage", 2001, "mobile",
                List.of(), false, 4);
        journey("loan_personal_papl_getEligibleLoanDetails", 2001, "mobile",
                List.of(), false, 6);
        journey("gi_gsa_purchase_validate_checks", 1001, "web",
                List.of(), false, 4);
        journey("home_dashboard_notification_getAllNotifications", 2001, "mobile",
                List.of(), false, 10);
        journey("home_dashboard_cards_getAllCCAccountSummary", 2001, "mobile",
                List.of("eis_cc_branchportal_account_cifAssociatedAccount"), false, 8);
        journey("home_user_preferred_lang_set", 2001, "mobile",
                List.of(), false, 5);
        journey("feedback_customer_txn-counter-and-rules_fetch", 2001, "mobile",
                List.of(), false, 6);
        journey("billpay_autopay_pendingbills_fetch", 2001, "mobile",
                List.of("unipay_payment_billpay_autopay_pendingbills",
                        "unipay_payment_billpay_autopay_get_active_activebillshistory"), false, 7);
        journey("billpay_autopay_favouritebillers_query", 2001, "mobile",
                List.of("unipay_payment_billpay_autopay_query_favouritebillers"), false, 6);
        journey("ops_martech_audience_refresh_execute", 2001, "mobile",
                List.of(), true, 0.6);
        journey("ops_eis_config_deploy_execute", 2001, "mobile",
                List.of(), true, 0.6);
    }

    private RoutingTable() {
    }

    private static void route(String id, String system, String tag, String url, String label,
                              double median, double sigma, String kind) {
        ROUTES.put(id, new Route(id, system, tag, url, label, median, sigma, kind));
    }

    private static void journey(String cmndId, int chnl, String channel, List<String> down,
                                boolean ops, double weight) {
        JOURNEYS.put(cmndId, new Journey(cmndId, chnl, channel, down, ops, weight));
    }

    public static Route route(String srvcId) {
        return ROUTES.get(srvcId);
    }

    public static Journey journey(String cmndId) {
        return JOURNEYS.get(cmndId);
    }

    public static List<Journey> journeys() {
        return List.copyOf(JOURNEYS.values());
    }

    // ---- request/response payload envelopes (verbatim shapes) --------------

    /** biz_req_input per journey (a small JSON body echoing the sample vocabulary). */
    public static String bizReqInput(Journey j, Session s) {
        Map<String, Object> m = Json.map();
        switch (j.cmndId()) {
            case "martech_hyper-personalization_offers_fetch" -> {
                m.put("offerFields", "persona|audienceId|businessArea|creativeUrl|marketingOfferMessage"
                        + "|ctaUrl|thumbnailUrl|messageHeader");
                m.put("numberRequested", "12|5|1|5|5");
                m.put("interactionPoint", "ip_stories|ip_cards|ip_greetings|ip_nudges|ip_banners");
            }
            case "loan_personal_papl_getEligibleLoanDetails" ->
                    m.putAll(Map.of("srcId", "Y2", "cstmrNm", "\u00e2\u20ac\u00a2", "rqstRfrncNmbr", "0"));
            case "lending_demand_demand-loan-closure_manage" ->
                    m.putAll(Map.of("refNo", "SBIY22" + IdGen.reqNoWeb().substring(8), "action", "Y"));
            case "gi_gsa_purchase_validate_checks" -> m.put("productCode", "GSA001");
            case "home_user_preferred_lang_set" -> m.put("preferredLang", "en_US");
            case "home_dashboard_notification_getAllNotifications" -> {
                Map<String, Object> req = Json.map();
                req.put("usrId", s.usrId);
                req.put("chnlId", 1);
                req.put("offset", 0);
                m.put("GetAllInappNotifReq", req);
            }
            case "home_dashboard_cards_getAllCCAccountSummary" -> m.put("usr_id", s.usrId);
            case "pfm_financial-fitness_consent_fetch" -> m.put("consentID", "1106036");
            case "auth_login_user_authenticate" ->
                    m.putAll(Map.of("loginMode", "MPIN", "deviceId", "XXXXXXXXXX"));
            case "upi_payment_send_money" ->
                    m.putAll(Map.of("payeeVpa", "XXX@upi", "amount", "XXX", "remarks", "payment"));
            default -> {
                // empty body for the remaining lightweight fetches
            }
        }
        return Json.str(m);
    }

    /** srvc_rqst envelope for a downstream route. */
    public static String srvcRqst(Route r, Session s, String rqstId) {
        Map<String, Object> m = Json.map();
        switch (r.kind()) {
            case "EIS_MARTECH" -> {
                m.put("TXN_TYPE", "INTERACT");
                m.put("SOURCE_ID", "Y2");
                m.put("DESTINATION", "MARTECH_DWH");
                Map<String, Object> payload = Json.map();
                payload.put("audienceLevel", "NOVAR_CIF");
                payload.put("cif", s.cif);
                m.put("EIS_PAYLOAD", payload);
            }
            case "EIS_TOKEN" -> {
                m.put("TXN_TYPE", "THINK360");
                m.put("SOURCE_ID", "Y2");
                m.put("DESTINATION", "IT_JVP");
                Map<String, Object> body = Json.map();
                body.put("username", "XXX");
                body.put("password", "XXX");
                Map<String, Object> payload = Json.map();
                payload.put("BODY", body);
                payload.put("HEADERS", Json.map());
                m.put("EIS_PAYLOAD", payload);
                m.put("TXN_SUB_TYPE", "LOGIN");
                m.put("REQUEST_REFERENCE_NUMBER", rqstId);
            }
            case "EIS_THINK360" -> {
                m.put("TXN_TYPE", "THINK360");
                m.put("SOURCE_ID", "Y2");
                m.put("DESTINATION", "IT_JVP");
                Map<String, Object> body = Json.map();
                body.put("user_id", s.usrRltnshpNo);
                body.put("account_id", "overall");
                Map<String, Object> payload = Json.map();
                payload.put("BODY", body);
                m.put("EIS_PAYLOAD", payload);
                m.put("TXN_SUB_TYPE", "FFS_FETCH_SUMMARY");
                m.put("REQUEST_REFERENCE_NUMBER", rqstId);
            }
            case "EIS_IAM" -> {
                m.put("SOURCE_ID", "Y2");
                Map<String, Object> body = Json.map();
                body.put("username", "XXX");
                body.put("loginMode", "MPIN");
                Map<String, Object> payload = Json.map();
                payload.put("BODY", body);
                m.put("EIS_PAYLOAD", payload);
                m.put("TXN_SUB_TYPE", "AUTHENTICATE");
                m.put("REQUEST_REFERENCE_NUMBER", rqstId);
            }
            case "EIS_CUSTPROFILE" -> {
                m.put("SOURCE_ID", "Y2");
                m.put("CUSTOMER_NUMBER", String.valueOf(s.usrRltnshpNo));
            }
            case "EIS_CIF" -> {
                m.put("SOURCE_ID", "Y2");
                Map<String, Object> payload = Json.map();
                payload.put("ACCOUNT_TYPE", "CO");
                payload.put("ACCOUNT_STATUS", "O");
                payload.put("CIF_DETAILS_REQ", "Y");
                payload.put("CUSTOMER_NUMBER", "XXXXXXXXXXX");
                payload.put("ACCOUNT_DETAILS_REQ", "Y");
                m.put("EIS_PAYLOAD", payload);
            }
            default -> { // UNIPAY
                Map<String, Object> head = Json.map();
                head.put("ts", java.time.OffsetDateTime.now().toString());
                head.put("requestId", rqstId);
                m.put("head", head);
                Map<String, Object> cust = Json.map();
                cust.put("cif", s.cif);
                cust.put("mobile", "9912303993");
                m.put("customerDetails", cust);
            }
        }
        return Json.str(m);
    }

    /** srvc_rspn envelope for a downstream route (success path). */
    public static String srvcRspnSuccess(Route r, boolean noDataFound) {
        return switch (r.kind()) {
            case "EIS_MARTECH", "EIS_IAM" -> eisResponse(200, true, "OK");
            case "EIS_TOKEN" -> {
                Map<String, Object> resp = Json.map();
                resp.put("expiry", (System.currentTimeMillis() / 1000L) + 3600);
                resp.put("success", true);
                resp.put("access_token", jwt());
                yield eisEnvelope("", resp);
            }
            case "EIS_THINK360" -> noDataFound
                    ? eisResponse(404, false, "Data Not Found")
                    : eisResponse(200, true, "OK");
            case "EIS_CUSTPROFILE", "EIS_CIF" -> {
                Map<String, Object> resp = Json.map();
                resp.put("PAN", "XXXXXXXXXX");
                resp.put("CUSTOMER_NUMBER", "XXXXXXXXXXX");
                resp.put("KYC_STATUS", "Y");
                resp.put("CIF_STATUS", "000");
                resp.put("ERROR_CODE", "");
                yield eisEnvelope("", resp);
            }
            default -> unipayReason("200", "No data found", null, null);
        };
    }

    /** srvc_rspn envelope for a UNIPAY business-failure-inside-success. */
    public static String unipayBusinessFailure(String complianceReason, String complianceRespCd) {
        return unipayReason("001", "Failure", complianceReason, complianceRespCd);
    }

    /** srvc_rspn for a token-expired EIS access token call. */
    public static String eisTokenExpired() {
        return eisResponse(401, false, "Token expired");
    }

    /** srvc_rspn for a hard transport failure (empty body, like the sample). */
    public static String emptyResponse() {
        return "{}";
    }

    private static String eisResponse(int statusCode, boolean success, String message) {
        Map<String, Object> resp = Json.map();
        resp.put("status_code", statusCode);
        resp.put("success", success);
        resp.put("message", message);
        return eisEnvelope("", resp);
    }

    private static String eisEnvelope(String errorCode, Map<String, Object> eisResponse) {
        Map<String, Object> m = Json.map();
        m.put("ERROR_CODE", errorCode);
        m.put("EIS_RESPONSE", eisResponse);
        m.put("RESPONSE_STATUS", "0");
        m.put("ERROR_DESCRIPTION", "");
        return Json.str(m);
    }

    private static String unipayReason(String code, String reason, String complianceReason,
                                       String complianceRespCd) {
        Map<String, Object> head = Json.map();
        head.put("ts", java.time.OffsetDateTime.now().toString());
        head.put("requestId", IdGen.downstreamReqId());
        Map<String, Object> reasonM = Json.map();
        reasonM.put("responseCode", code);
        reasonM.put("responseReason", reason);
        if (complianceReason != null) {
            reasonM.put("complianceReason", complianceReason);
        }
        if (complianceRespCd != null) {
            reasonM.put("complianceRespCd", complianceRespCd);
        }
        Map<String, Object> m = Json.map();
        m.put("head", head);
        m.put("reason", reasonM);
        return Json.str(m);
    }

    private static String jwt() {
        return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + IdGen.reqNoHex() + "." + IdGen.reqNoHex();
    }
}
