package com.sbi.novasim;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

import org.apache.logging.log4j.ThreadContext;

/**
 * Drives the NOVA 2.0 journey mesh: fires ~rate journey-actions/second across a
 * session pool. Each action mints a fresh trns_id, emits one audit_transaction,
 * 0..n audit_service downstream calls, service_metrics, and (on failure) an
 * audit_error — all in the contract shapes. Scenario effects are consulted
 * generically via {@link ScenarioEngine}; no scenario name is ever emitted.
 */
public final class JourneyEngine {

    private static final String USR_TYP = "ETB_CUSTOMER";
    private static final int JOURNEY_OVERHEAD_MS = 30;

    private final SessionPool pool;
    private final ScenarioEngine scenarios;

    private final ExecutorService workers = Executors.newFixedThreadPool(64, r -> {
        Thread t = new Thread(r, "nova-journey");
        t.setDaemon(true);
        return t;
    });
    private Thread driver;

    private final AtomicBoolean running = new AtomicBoolean(false);
    private volatile double rate;

    private final AtomicLong txnCount = new AtomicLong();
    private final AtomicLong errCount = new AtomicLong();
    private final AtomicLong svcCount = new AtomicLong();

    private final double totalWeight;

    public JourneyEngine(SessionPool pool, ScenarioEngine scenarios, double rate) {
        this.pool = pool;
        this.scenarios = scenarios;
        this.rate = rate;
        double w = 0;
        for (RoutingTable.Journey j : RoutingTable.journeys()) {
            w += j.weight();
        }
        this.totalWeight = w;
    }

    public void start() {
        if (running.getAndSet(true)) {
            return;
        }
        driver = new Thread(this::loop, "nova-driver");
        driver.setDaemon(true);
        driver.start();
    }

    public void stop() {
        running.set(false);
        workers.shutdown();
    }

    public void setRate(double r) {
        this.rate = Math.max(0.1, r);
    }

    public double rate() {
        return rate;
    }

    public long txnCount() {
        return txnCount.get();
    }

    public long errCount() {
        return errCount.get();
    }

    public long svcCount() {
        return svcCount.get();
    }

    private void loop() {
        while (running.get()) {
            try {
                RoutingTable.Journey j = pickJourney();
                Session s = pool.random();
                workers.submit(() -> safeAction(j, s, null, false));
                long interval = Math.max(1L, (long) (1000.0 / rate));
                Thread.sleep(interval);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            } catch (RuntimeException e) {
                System.err.println("[novasim] driver error: " + e.getMessage());
            }
        }
    }

    private RoutingTable.Journey pickJourney() {
        double pick = ThreadLocalRandom.current().nextDouble() * totalWeight;
        double acc = 0;
        for (RoutingTable.Journey j : RoutingTable.journeys()) {
            acc += j.weight();
            if (pick <= acc) {
                return j;
            }
        }
        return RoutingTable.journeys().get(0);
    }

    // ---- scenario-driven one-shots -----------------------------------------

    /** Fire a single ops/audit transaction (always success). Used by ops_txn. */
    public void fireOps(String cmndId) {
        RoutingTable.Journey j = RoutingTable.journey(cmndId);
        if (j != null) {
            workers.submit(() -> safeAction(j, pool.random(), null, true));
        }
    }

    /** Replay one client's identical failing request {@code count} times. */
    public void fireReplay(String cmndId, int count, String errCd) {
        RoutingTable.Journey j = RoutingTable.journey(cmndId);
        if (j == null) {
            return;
        }
        Session victim = pool.random();
        String fixedReq = RoutingTable.bizReqInput(j, victim);
        String code = (errCd == null || errCd.isBlank()) ? "5151" : errCd;
        for (int i = 0; i < count; i++) {
            final int idx = i;
            workers.submit(() -> {
                try {
                    Thread.sleep(idx * 350L);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
                safeAction(j, victim, new Replay(code, fixedReq), false);
            });
        }
    }

    private record Replay(String errCd, String fixedReqInput) {
    }

    private void safeAction(RoutingTable.Journey j, Session s, Replay replay, boolean forceOk) {
        try {
            doAction(j, s, replay, forceOk);
        } catch (RuntimeException e) {
            System.err.println("[novasim] action error (" + j.cmndId() + "): " + e.getMessage());
        }
    }

    // ---- one journey action ------------------------------------------------

    private record DResult(long durationMs, boolean transportOk, boolean businessOk,
                           boolean blocking, String journeyErrCd, boolean journeyBusiness,
                           String journeyBizCode) {
    }

    private void doAction(RoutingTable.Journey j, Session s, Replay replay, boolean forceOk) {
        String trnsId = IdGen.tokenId();
        ThreadContext.put("trnsId", trnsId);
        ThreadContext.put("sessnTknId", s.sessnTknId);
        try {
            long start = System.currentTimeMillis();
            long cursor = start;

            boolean blocked = false;
            String journeyErrCd = null;
            boolean journeyBusiness = false;
            String journeyBizCode = null;

            if (replay == null) {
                for (String srvcId : j.downstream()) {
                    Route r = RoutingTable.route(srvcId);
                    DResult dr = callDownstream(r, s, trnsId, cursor);
                    cursor += dr.durationMs();
                    if (dr.blocking() && !blocked) {
                        blocked = true;
                        journeyErrCd = dr.journeyErrCd();
                        journeyBusiness = dr.journeyBusiness();
                        journeyBizCode = dr.journeyBizCode();
                        break; // chain stops at the first hard failure
                    }
                }
            }

            // Journey-level latency (own processing + scenario route_latency on cmndId).
            double ownMedian = scenarios.latencyMedianMs(j.cmndId(), JOURNEY_OVERHEAD_MS);
            long ownMs = sample(ownMedian, 0.3);
            long end = cursor + ownMs;

            // Resolve final outcome.
            boolean error;
            String errCd = null;
            boolean business = false;
            String bizCode = null;

            if (replay != null) {
                error = true;
                errCd = replay.errCd();
                business = false;
            } else if (forceOk || j.ops()) {
                error = false; // ops/audit journeys always succeed
            } else {
                ScenarioEngine.ForcedError fe = scenarios.forcedError(j.cmndId());
                String bf = scenarios.businessFailure(j.cmndId());
                if (fe != null) {
                    error = true;
                    errCd = fe.errCd();
                    business = false;
                } else if (bf != null) {
                    error = true;
                    business = true;
                    bizCode = bf;
                    errCd = "BS000001";
                } else if (blocked) {
                    error = true;
                    business = journeyBusiness;
                    bizCode = journeyBizCode;
                    errCd = journeyErrCd;
                } else if (isPaplNoise(j)) {
                    error = true;
                    business = true;
                    bizCode = "BSPAPL010";
                    errCd = "BS000001";
                } else {
                    error = false;
                }
            }

            emitTransaction(j, s, trnsId, start, end, error, replay);
            if (error) {
                emitError(j, s, trnsId, end, errCd, business, bizCode);
                errCount.incrementAndGet();
            }

            String system = primarySystem(j);
            MetricsEmitter.journey(j.cmndId(), system, j.cmndId(), end - start, !error, !error);
            txnCount.incrementAndGet();
        } finally {
            IdGen.releaseSeq(trnsId);
            ThreadContext.clearMap();
        }
    }

    private static boolean isPaplNoise(RoutingTable.Journey j) {
        return "loan_personal_papl_getEligibleLoanDetails".equals(j.cmndId())
                && ThreadLocalRandom.current().nextDouble() < 0.03;
    }

    private String primarySystem(RoutingTable.Journey j) {
        if (j.downstream().isEmpty()) {
            return "NOVA2";
        }
        Route r = RoutingTable.route(j.downstream().get(0));
        return r == null ? "NOVA2" : r.systemTag();
    }

    // ---- downstream call ---------------------------------------------------

    private DResult callDownstream(Route r, Session s, String trnsId, long dStrt) {
        double median = scenarios.latencyMedianMs(r.srvcId(), r.medianMs());
        long dur = sample(median, r.sigma());
        long dEnd = dStrt + dur;

        boolean unipay = "UNIPAY".equals(r.systemTag());
        Object trnsSts;
        Object errCd;
        String errMsg;
        String srvcRspn;
        boolean transportOk;
        boolean businessOk;
        boolean blocking = false;
        String journeyErrCd = null;
        boolean journeyBusiness = false;
        String journeyBizCode = null;

        ScenarioEngine.ForcedError fe = scenarios.forcedError(r.srvcId());
        boolean tokenExpired = scenarios.tokenExpired(r.srvcId());
        String bizFail = scenarios.businessFailure(r.srvcId());

        if (fe != null) {
            // Hard transport/technical failure.
            trnsSts = unipay ? "-2" : Integer.valueOf(-2);
            errCd = fe.errCd();
            errMsg = fe.errMsg();
            srvcRspn = RoutingTable.emptyResponse();
            transportOk = false;
            businessOk = false;
            blocking = true;
            journeyErrCd = journeyErrFor(r);
            journeyBusiness = isMartech(r);
            journeyBizCode = isMartech(r) ? "BSYHP003" : null;
        } else if (tokenExpired) {
            // Layered: transport ok, business (token) fails -> cascades to journey.
            trnsSts = unipay ? "success" : Integer.valueOf(0);
            errCd = "";
            errMsg = "";
            srvcRspn = RoutingTable.eisTokenExpired();
            transportOk = true;
            businessOk = false;
            blocking = true;
            journeyErrCd = "5151";
            journeyBusiness = false;
        } else if (bizFail != null) {
            // Business-failure-inside-success (silent — no status field turns red).
            transportOk = true;
            businessOk = false;
            if (unipay) {
                trnsSts = "success";
                errCd = 1;
                errMsg = "Failure";
                srvcRspn = RoutingTable.unipayBusinessFailure(bizFail, complianceMsg(bizFail));
            } else {
                trnsSts = 0;
                errCd = "";
                errMsg = "";
                srvcRspn = RoutingTable.srvcRspnSuccess(r, true);
            }
        } else {
            // Normal success (with the authentic noise floor).
            transportOk = true;
            businessOk = true;
            boolean noise = ThreadLocalRandom.current().nextDouble() < 0.05;
            if (unipay) {
                if (noise) {
                    // low-rate benign business-failure-inside-success
                    businessOk = false;
                    trnsSts = "success";
                    errCd = 1;
                    errMsg = "Failure";
                    srvcRspn = RoutingTable.unipayBusinessFailure("BFR003", complianceMsg("BFR003"));
                } else {
                    trnsSts = "success";
                    errCd = 200;
                    errMsg = "No data found";
                    srvcRspn = RoutingTable.srvcRspnSuccess(r, true);
                }
            } else {
                trnsSts = 0;
                errCd = null;
                errMsg = null;
                srvcRspn = RoutingTable.srvcRspnSuccess(r, noise);
                if (noise) {
                    businessOk = false;
                }
            }
        }

        String rqstId = IdGen.downstreamReqId();
        emitService(r, s, trnsId, trnsSts, errCd, errMsg,
                RoutingTable.srvcRqst(r, s, rqstId), srvcRspn, rqstId, dStrt, dEnd);
        MetricsEmitter.downstream(r.srvcId(), r.systemTag(), r.routeLabel(), dur, transportOk, businessOk);

        return new DResult(dur, transportOk, businessOk, blocking, journeyErrCd, journeyBusiness,
                journeyBizCode);
    }

    private static boolean isMartech(Route r) {
        return "eis_marTech_getInteractOffers".equals(r.srvcId());
    }

    private static String journeyErrFor(Route r) {
        // Martech downstream failure surfaces as a business exception journey-side;
        // every other technical/transport failure surfaces as legacy code 5151.
        return isMartech(r) ? "BS000001" : "5151";
    }

    private static String complianceMsg(String code) {
        return switch (code) {
            case "BFR003" -> "No bill data available";
            default -> "Compliance check failed";
        };
    }

    // ---- document builders -------------------------------------------------

    private void emitTransaction(RoutingTable.Journey j, Session s, String trnsId, long start,
                                 long end, boolean error, Replay replay) {
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("msg_id", IdGen.msgId());
        d.put("trns_id", trnsId);
        d.put("sessn_tkn_id", s.sessnTknId);
        d.put("clnt_ip_addr", s.clntIpAddr);
        d.put("req_no", j.chnlId() == 1001 ? IdGen.reqNoWeb() : IdGen.reqNoHex());
        d.put("usr_rltnshp_no", String.valueOf(s.usrRltnshpNo));
        d.put("trns_stts", error ? "error" : "success");
        d.put("strt_time", Instant.ofEpochMilli(start).toString());
        d.put("end_time", Instant.ofEpochMilli(end).toString());
        d.put("usr_id", s.usrId);
        d.put("usr_typ", USR_TYP);
        d.put("cmnd_id", j.cmndId());
        d.put("chnl_id", j.chnlId());
        String reqInput = replay != null ? replay.fixedReqInput() : RoutingTable.bizReqInput(j, s);
        d.put("biz_req_input", reqInput);
        d.put("biz_resp_output", bizRespOutput(j, error));
        d.put("crtd_by", "TransAdtUser");
        d.put("crtd_on", Instant.ofEpochMilli(end + 3).toString());
        // trace_id is mostly the literal "NULL"; occasionally a hex id on errors.
        d.put("trace_id", (error && ThreadLocalRandom.current().nextDouble() < 0.3)
                ? IdGen.traceHex() : "NULL");
        d.put("nfrchk", "NULL");
        d.put("seq", IdGen.nextSeq(trnsId));
        d.put("channel", j.channel());
        Emit.doc("audit_transaction", d);
    }

    private String bizRespOutput(RoutingTable.Journey j, boolean error) {
        if (error) {
            return "{}";
        }
        // Success responses are frequently double-encoded (JSON-in-JSON-string).
        double roll = ThreadLocalRandom.current().nextDouble();
        if (roll < 0.30) {
            Map<String, Object> inner = Json.map();
            inner.put("navigateToNextPage", false);
            return Json.doubleEncoded("response", inner);
        }
        if (roll < 0.45) {
            Map<String, Object> inner = Json.map();
            inner.put("status", "Success");
            return Json.str(inner);
        }
        return "{}";
    }

    private void emitService(Route r, Session s, String trnsId, Object trnsSts, Object errCd,
                             String errMsg, String srvcRqst, String srvcRspn, String rqstId,
                             long dStrt, long dEnd) {
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("msg_id", IdGen.msgId());
        d.put("trns_id", trnsId);
        d.put("sessn_tkn_id", s.sessnTknId);
        d.put("trns_sts", trnsSts);
        d.put("err_cd", errCd);
        d.put("err_msg", errMsg);
        d.put("usr_id", s.usrId);
        // srvc_rspn is double-encoded at a low rate to exercise the decoder.
        boolean doubleEnc = ThreadLocalRandom.current().nextDouble() < 0.08;
        d.put("srvc_rqst", srvcRqst);
        d.put("srvc_rspn", doubleEnc ? Json.doubleEncoded("payload", rawOrEmpty(srvcRspn)) : srvcRspn);
        d.put("srvc_id", r.srvcId());
        d.put("systm_nm", r.system());
        d.put("api_url", r.apiUrl());
        d.put("rqst_id_sent", rqstId);
        d.put("rqst_id_rcvd", rqstId);
        d.put("crtd_by", "ServiceAdtUser");
        d.put("crtd_on", Instant.ofEpochMilli(dEnd + 4).toString());
        d.put("strt_time", Instant.ofEpochMilli(dStrt).toString());
        d.put("end_time", Instant.ofEpochMilli(dEnd).toString());
        d.put("seq", IdGen.nextSeq(trnsId));
        Emit.doc("audit_service", d);
        svcCount.incrementAndGet();
    }

    private static Object rawOrEmpty(String json) {
        return json == null ? "{}" : json;
    }

    private void emitError(RoutingTable.Journey j, Session s, String trnsId, long end, String errCd,
                           boolean business, String bizCode) {
        Map<String, Object> d = new LinkedHashMap<>();
        d.put("msg_id", IdGen.msgId());
        d.put("trns_id", trnsId);
        d.put("sessn_tkn_id", s.sessnTknId);
        if (business) {
            d.put("err_cd", "BS000001");
            d.put("err_typ", "BUSINESS_EXCEPTION");
            d.put("err_dscrptn", "Business Exception Occured");
            d.put("err_dtls", ErrorCatalog.errDtls(bizCode));
        } else {
            d.put("err_cd", errCd);
            d.put("err_typ", "TECHNICAL_EXCEPTION");
            d.put("err_dscrptn", ErrorCatalog.techDscrptn(errCd));
            d.put("err_dtls", "NULL");
        }
        d.put("crtd_by", "ErrorAdtUser");
        d.put("crtd_on", Instant.ofEpochMilli(end + 3).toString());
        d.put("err_time", Instant.ofEpochMilli(end).toString());
        d.put("usr_id", s.usrId);
        for (int i = 1; i <= 5; i++) {
            boolean first = i == 1 && business;
            d.put("biz_err_cd_" + i, first ? bizCode : "NULL");
            d.put("biz_err_cd_" + i + "_msg", first ? ErrorCatalog.bizMessage(bizCode) : "NULL");
        }
        d.put("seq", IdGen.nextSeq(trnsId));
        Emit.doc("audit_error", d);
    }

    // ---- latency sampling --------------------------------------------------

    /** Log-normal sample around a median with the given sigma; floored at 5ms. */
    private static long sample(double median, double sigma) {
        double v = median * Math.exp(sigma * ThreadLocalRandom.current().nextGaussian());
        return Math.max(5L, (long) v);
    }

    public void shutdownNow() {
        running.set(false);
        workers.shutdownNow();
    }
}
