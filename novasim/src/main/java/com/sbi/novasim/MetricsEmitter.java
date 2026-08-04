package com.sbi.novasim;

import java.time.Instant;
import java.util.Map;

/**
 * Emits one {@code service_metrics} time-series document per journey action and
 * per downstream call. service_metrics is a timeseries collection, so these are
 * ordinary inserts (the appender never does anything special for them).
 */
public final class MetricsEmitter {

    private MetricsEmitter() {
    }

    public static void journey(String cmndId, String system, String route, long durationMs,
                               boolean transportOk, boolean businessOk) {
        emit(cmndId, system, "journey", route, durationMs, transportOk, businessOk);
    }

    public static void downstream(String srvcId, String systemTag, String route, long durationMs,
                                  boolean transportOk, boolean businessOk) {
        emit(srvcId, systemTag, "downstream", route, durationMs, transportOk, businessOk);
    }

    private static void emit(String service, String system, String kind, String route,
                             long durationMs, boolean transportOk, boolean businessOk) {
        Map<String, Object> meta = Json.map();
        meta.put("service", service);
        meta.put("system", system);
        meta.put("kind", kind);
        meta.put("route", route);

        Map<String, Object> doc = Json.map();
        // ts is a real Date; the appender treats non-date keys as pass-through,
        // so hand it an already-typed Date rather than an ISO string.
        doc.put("ts", java.util.Date.from(Instant.now()));
        doc.put("meta", meta);
        doc.put("durationMs", (int) durationMs);
        doc.put("transportOk", transportOk);
        doc.put("businessOk", businessOk);

        Emit.doc("service_metrics", doc);
    }
}
