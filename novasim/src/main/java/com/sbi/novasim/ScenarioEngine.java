package com.sbi.novasim;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;

/**
 * Loads data-only scenario files and applies their effects via a small set of
 * GENERIC interpreters. No scenario name is ever written into an emitted
 * document; the engine only toggles route latency / error / business-failure
 * behaviour that {@link JourneyEngine} consults while producing ordinary traffic.
 */
public final class ScenarioEngine {

    /** The injectable scenarios (files live in resources/scenarios/); simple headline ones first. */
    public static final List<String> SCENARIO_IDS = List.of(
            "login-failures",
            "upi-payment-failures",
            "eis-martech-brownout",
            "martech-cif-desync",
            "think360-token-expiry",
            "unipay-bbps-brownout",
            "gsa-validation-hang",
            "demand-loan-improper-response",
            "poison-retry-loop",
            "eis-gateway-pool-exhaustion");

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    /** A forced downstream error result. */
    public record ForcedError(String errCd, String errMsg, int transStatus) {
    }

    /** An effect currently in force. */
    private static final class Active {
        final String kind;
        final Map<String, Object> params;
        final long from;
        final long until;

        Active(String kind, Map<String, Object> params, long from, long until) {
            this.kind = kind;
            this.params = params;
            this.from = from;
            this.until = until;
        }

        boolean live(long now) {
            return now >= from && now <= until;
        }
    }

    private final CopyOnWriteArrayList<Active> active = new CopyOnWriteArrayList<>();
    private final ScheduledExecutorService sched =
            Executors.newScheduledThreadPool(2, r -> {
                Thread t = new Thread(r, "nova-scenario");
                t.setDaemon(true);
                return t;
            });

    private volatile JourneyEngine journeys;
    private volatile String lastFired = "-";

    public void bind(JourneyEngine engine) {
        this.journeys = engine;
    }

    public String lastFired() {
        return lastFired;
    }

    public int activeCount() {
        long now = System.currentTimeMillis();
        int n = 0;
        for (Active a : active) {
            if (a.live(now)) {
                n++;
            }
        }
        return n;
    }

    public Scenario load(String id) {
        String path = "/scenarios/" + id + ".json";
        try (InputStream in = ScenarioEngine.class.getResourceAsStream(path)) {
            if (in == null) {
                throw new IllegalArgumentException("unknown scenario '" + id + "'");
            }
            return MAPPER.readValue(in, Scenario.class);
        } catch (Exception e) {
            throw new IllegalArgumentException("could not load scenario '" + id + "': " + e.getMessage(), e);
        }
    }

    /** Fire a scenario once. {@code burst} repeats it; {@code delayMs} defers the start. */
    public void fire(String id, int burst, long delayMs) {
        Scenario sc = load(id); // validate up-front
        lastFired = id;
        for (int b = 0; b < Math.max(1, burst); b++) {
            long offset = delayMs + (long) b * (sc.durationSeconds * 1000L + 1500L);
            sched.schedule(() -> apply(sc), offset, TimeUnit.MILLISECONDS);
        }
    }

    private void apply(Scenario sc) {
        long start = System.currentTimeMillis();
        long end = start + sc.durationSeconds * 1000L;
        System.err.println("[novasim] scenario applied (id-internal), duration="
                + sc.durationSeconds + "s, effects=" + sc.effects.size());
        for (Scenario.Effect e : sc.effects) {
            Map<String, Object> params = e.params == null ? Map.of() : e.params;
            switch (e.kind) {
                case "route_latency", "route_error_rate", "business_failure_rate", "token_expiry" ->
                        sched.schedule(
                                () -> active.add(new Active(e.kind, params,
                                        System.currentTimeMillis(), end)),
                                e.atOffsetMs, TimeUnit.MILLISECONDS);
                case "ops_txn" -> sched.schedule(() -> fireOps(params), e.atOffsetMs, TimeUnit.MILLISECONDS);
                case "client_replay" ->
                        sched.schedule(() -> fireReplay(params), e.atOffsetMs, TimeUnit.MILLISECONDS);
                default -> System.err.println("[novasim] unknown effect kind: " + e.kind);
            }
        }
        // Sweep expired effects shortly after the window closes.
        sched.schedule(this::sweep, sc.durationSeconds * 1000L + 500L, TimeUnit.MILLISECONDS);
    }

    private void sweep() {
        long now = System.currentTimeMillis();
        active.removeIf(a -> now > a.until);
    }

    private void fireOps(Map<String, Object> params) {
        JourneyEngine je = journeys;
        if (je != null) {
            je.fireOps(str(params, "cmndId"));
        }
    }

    private void fireReplay(Map<String, Object> params) {
        JourneyEngine je = journeys;
        if (je != null) {
            je.fireReplay(str(params, "cmndId"), intParam(params, "count", 10),
                    str(params, "errCd"));
        }
    }

    // ---- generic queries consulted by JourneyEngine ------------------------

    /** Effective median latency for a route key, applying any active ramp. */
    public double latencyMedianMs(String routeKey, double base) {
        long now = System.currentTimeMillis();
        double best = base;
        for (Active a : active) {
            if (!"route_latency".equals(a.kind) || !a.live(now)) {
                continue;
            }
            if (!routeKey.equals(str(a.params, "srvcId")) && !routeKey.equals(str(a.params, "cmndId"))) {
                continue;
            }
            double target = intParam(a.params, "targetMs", (int) base);
            double ramp = Math.max(1, intParam(a.params, "rampMs", 1));
            double progress = Math.min(1.0, Math.max(0.0, (now - a.from) / ramp));
            double eff = base + (target - base) * progress;
            best = Math.max(best, eff);
        }
        return best;
    }

    /** A forced transport/technical error for a route, applied at its rate. */
    public ForcedError forcedError(String routeKey) {
        long now = System.currentTimeMillis();
        for (Active a : active) {
            if (!"route_error_rate".equals(a.kind) || !a.live(now)) {
                continue;
            }
            if (!routeKey.equals(str(a.params, "srvcId")) && !routeKey.equals(str(a.params, "cmndId"))) {
                continue;
            }
            if (ThreadLocalRandom.current().nextDouble() < dbl(a.params, "rate", 1.0)) {
                int trans = a.params.containsKey("transStatus")
                        ? intParam(a.params, "transStatus", -2) : -2;
                return new ForcedError(str(a.params, "errCd"), str(a.params, "errMsg"), trans);
            }
        }
        return null;
    }

    /** A compliance code for a business-failure-inside-success, applied at its rate. */
    public String businessFailure(String routeKey) {
        long now = System.currentTimeMillis();
        for (Active a : active) {
            if (!"business_failure_rate".equals(a.kind) || !a.live(now)) {
                continue;
            }
            if (!routeKey.equals(str(a.params, "srvcId")) && !routeKey.equals(str(a.params, "cmndId"))) {
                continue;
            }
            if (ThreadLocalRandom.current().nextDouble() < dbl(a.params, "rate", 1.0)) {
                return str(a.params, "complianceCode");
            }
        }
        return null;
    }

    /** True while a token_expiry effect is active for the route. */
    public boolean tokenExpired(String routeKey) {
        long now = System.currentTimeMillis();
        for (Active a : active) {
            if ("token_expiry".equals(a.kind) && a.live(now)
                    && routeKey.equals(str(a.params, "srvcId"))) {
                return true;
            }
        }
        return false;
    }

    public void shutdown() {
        sched.shutdownNow();
    }

    // ---- param helpers -----------------------------------------------------

    private static String str(Map<String, Object> p, String key) {
        Object v = p.get(key);
        return v == null ? null : v.toString();
    }

    private static int intParam(Map<String, Object> p, String key, int def) {
        Object v = p.get(key);
        if (v instanceof Number n) {
            return n.intValue();
        }
        if (v != null) {
            try {
                return Integer.parseInt(v.toString());
            } catch (NumberFormatException ignore) {
                return def;
            }
        }
        return def;
    }

    private static double dbl(Map<String, Object> p, String key, double def) {
        Object v = p.get(key);
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        if (v != null) {
            try {
                return Double.parseDouble(v.toString());
            } catch (NumberFormatException ignore) {
                return def;
            }
        }
        return def;
    }
}
