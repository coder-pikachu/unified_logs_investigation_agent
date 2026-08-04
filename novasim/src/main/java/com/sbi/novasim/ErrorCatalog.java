package com.sbi.novasim;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Domain glossary of NOVA 2.0 error codes (business + technical) and how they
 * render into {@code audit_error} fields. This is reference data about the codes
 * themselves — NOT scenario logic. No scenario name appears here.
 */
public final class ErrorCatalog {

    /** A business error code and the message that always accompanies it. */
    public record Biz(String code, String message) {
    }

    private static final Map<String, String> BIZ_MSG = new LinkedHashMap<>();
    private static final Map<String, String> TECH_DSCRPTN = new LinkedHashMap<>();

    static {
        BIZ_MSG.put("BSYHP003", "CIF Is Not Recognized By Martech.");
        BIZ_MSG.put("BSPAPL010", "Sorry! This offer is not available to you.");
        BIZ_MSG.put("BSDML050",
                "Your Demand Loan closure request has failed. Kindly visit branch for further assistance.");
        BIZ_MSG.put("BSDML024",
                "We regret that your Demand Loan request could not be processed due to technical issue. "
                        + "Please try again after some time.");

        TECH_DSCRPTN.put("TEY2GSA02",
                "Technical Error: Exception occur during Request vaidation or processing failed "
                        + "due to unexpected data state");
        TECH_DSCRPTN.put("5151", "Exception occurred while executing the service");
        TECH_DSCRPTN.put("TEEIS009", "Response Transformation failed.");
    }

    private ErrorCatalog() {
    }

    public static String bizMessage(String code) {
        return BIZ_MSG.getOrDefault(code, "Business Exception Occured");
    }

    public static String techDscrptn(String code) {
        return TECH_DSCRPTN.getOrDefault(code, "Exception occurred while executing the service");
    }

    /**
     * Build the {@code err_dtls} JSON string keyed by business code. {@code BSDML050}
     * nests {@code BSDML024 -> loan_discharge: "received improper response"} to
     * reproduce the malformed-contract shape.
     */
    public static String errDtls(String bizCode) {
        Map<String, Object> root = new LinkedHashMap<>();
        if ("BSDML050".equals(bizCode)) {
            Map<String, Object> inner024Data = new LinkedHashMap<>();
            inner024Data.put("loan_discharge", "received improper response");
            Map<String, Object> inner024 = new LinkedHashMap<>();
            inner024.put("data", inner024Data);
            inner024.put("message", bizMessage("BSDML024"));
            Map<String, Object> data050 = new LinkedHashMap<>();
            data050.put("BSDML024", inner024);
            Map<String, Object> body050 = new LinkedHashMap<>();
            body050.put("data", data050);
            body050.put("message", bizMessage("BSDML050"));
            root.put("BSDML050", body050);
        } else {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("message", bizMessage(bizCode));
            root.put(bizCode, body);
        }
        return Json.str(root);
    }
}
