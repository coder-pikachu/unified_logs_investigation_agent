"""Prompt fragments shared by the LLM nodes. The field glossary is the single
most important one: the abbreviated NOVA field names confuse the model, so every
reasoning prompt carries this so nodes read journey/system/businessStatus rather
than raw abbreviations."""

GLOSSARY = """FIELD GLOSSARY (NOVA 2.0 audit logs):
- trns_id: transaction id, the primary correlation key joining all three collections.
- sessn_tkn_id: session token, groups many trns_id into one user session.
- cmnd_id: the journey/feature identifier (domain_module_feature_action), e.g. martech_hyper-personalization_offers_fetch.
- srvc_id: downstream/dependency operation id, e.g. eis_marTech_getInteractOffers.
- systm_nm: downstream system name (EIS, ' UNIPAY' — note leading space in data).
- trns_stts (audit_transaction, double-t) / trns_sts (audit_service, single-t): status. Values mix vocabularies: success | error | 0 (ok) | -2 (failure).
- err_cd: error code across mixed vocabularies: BS****/BSYHP***/BSDML*** (business), TE****/TEEIS009/TEY2GSA02 (technical), bare numerics (5151) legacy.
- err_dtls: JSON, possibly nested; the INNERMOST code names the real dependency failure (e.g. BSDML050 wraps BSDML024 -> "loan_discharge received improper response").
- biz_resp_output / srvc_rspn: JSON, often double-encoded. transport can succeed while business fails: UNIPAY {"reason":{"responseReason":"Failure","complianceReason":"BFR003"}}; EIS {"EIS_RESPONSE":{"status_code":404,"success":false}}.
- chnl_id: channel 2001 mobile, 1001 web.
KEY PRINCIPLE: status fields lie. Classify each event on BOTH transport and business status. The loudest (most frequent) error is usually a downstream symptom; the origin is the shared upstream dependency that failed first."""
