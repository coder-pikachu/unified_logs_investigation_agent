package com.sbi.novasim;

/**
 * A downstream/surrounding-system route.
 *
 * @param srvcId     downstream operation id (audit_service.srvc_id)
 * @param system     systm_nm exactly as stored (note {@code " UNIPAY"} leading space)
 * @param systemTag  trimmed system name for metrics ({@code EIS} / {@code UNIPAY})
 * @param apiUrl     lookalike host URL (never a real sbi.co.in host)
 * @param routeLabel coarse route grouping used in metrics + incident narratives
 * @param medianMs   log-normal median latency
 * @param sigma      log-normal sigma
 * @param kind       payload envelope family: EIS_MARTECH, EIS_TOKEN, EIS_THINK360,
 *                   EIS_CUSTPROFILE, EIS_CIF, UNIPAY
 */
public record Route(String srvcId, String system, String systemTag, String apiUrl,
                    String routeLabel, double medianMs, double sigma, String kind) {

    public static final String EIS = "EIS";
    public static final String UNIPAY = " UNIPAY"; // leading space is intentional
}
