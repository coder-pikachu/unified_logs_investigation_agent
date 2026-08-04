package com.sbi.novasim;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Generates ids that match the observed NOVA 2.0 formats.
 *
 * <p>trns_id / sessn_tkn_id: {@code <epochMillis><17-char alnum suffix>}, e.g.
 * {@code 1783420778003ix0AcsX0vwDd6c2bb}. seq: monotonic int per trns_id.
 */
public final class IdGen {

    private static final char[] ALNUM =
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".toCharArray();
    private static final char[] HEX = "0123456789abcdef".toCharArray();

    private static final int SUFFIX_LEN = 17;

    private static final ConcurrentHashMap<String, AtomicInteger> SEQ = new ConcurrentHashMap<>();

    private IdGen() {
    }

    /** trns_id / sessn_tkn_id: epoch-millis + random alphanumeric suffix. */
    public static String tokenId() {
        return tokenId(System.currentTimeMillis());
    }

    public static String tokenId(long epochMillis) {
        StringBuilder sb = new StringBuilder(13 + SUFFIX_LEN);
        sb.append(epochMillis);
        ThreadLocalRandom r = ThreadLocalRandom.current();
        for (int i = 0; i < SUFFIX_LEN; i++) {
            sb.append(ALNUM[r.nextInt(ALNUM.length)]);
        }
        return sb.toString();
    }

    /** 8-digit numeric msg_id domain widened; observed ids are large ints. */
    public static int msgId() {
        return ThreadLocalRandom.current().nextInt(10_000_000, 99_999_999);
    }

    /** Mobile req_no: 32-hex uuid-style string. */
    public static String reqNoHex() {
        StringBuilder sb = new StringBuilder(32);
        ThreadLocalRandom r = ThreadLocalRandom.current();
        for (int i = 0; i < 32; i++) {
            sb.append(HEX[r.nextInt(HEX.length)]);
        }
        return sb.toString();
    }

    /** Web req_no: {@code novaweb_<digits>}. */
    public static String reqNoWeb() {
        return "novaweb_" + ThreadLocalRandom.current().nextInt(100_000_000, 999_999_999);
    }

    /** Downstream request id: {@code SBIY22<digits>} / {@code SB41<...>} shaped. */
    public static String downstreamReqId() {
        StringBuilder sb = new StringBuilder("SBIY22");
        ThreadLocalRandom r = ThreadLocalRandom.current();
        for (int i = 0; i < 17; i++) {
            sb.append((char) ('0' + r.nextInt(10)));
        }
        return sb.toString();
    }

    /** 32-hex trace id (only occasionally used; usually the literal "NULL"). */
    public static String traceHex() {
        return reqNoHex();
    }

    /** Monotonic per-trns_id sequence, starting at 1. */
    public static int nextSeq(String trnsId) {
        return SEQ.computeIfAbsent(trnsId, k -> new AtomicInteger(0)).incrementAndGet();
    }

    /** Release the seq counter for a finished trns_id to bound the map. */
    public static void releaseSeq(String trnsId) {
        SEQ.remove(trnsId);
    }
}
