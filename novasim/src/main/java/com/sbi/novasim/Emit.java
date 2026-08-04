package com.sbi.novasim;

import java.util.Map;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;

/**
 * Single funnel for emitting documents. Builds a {@link DocMessage} tagged with
 * the target collection and logs it through the {@code nova.emit} logger, whose
 * config routes to the async Mongo appender (and the gated console mirror).
 */
public final class Emit {

    private static final Logger LOG = LogManager.getLogger("nova.emit");

    private Emit() {
    }

    /** Emit one document into {@code collection}. Fields are consumed as-is. */
    public static void doc(String collection, Map<String, Object> fields) {
        fields.put("_collection", collection);
        LOG.info(new DocMessage(fields));
    }
}
