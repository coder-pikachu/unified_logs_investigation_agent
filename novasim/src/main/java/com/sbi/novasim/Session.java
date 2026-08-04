package com.sbi.novasim;

import java.util.concurrent.ThreadLocalRandom;

/**
 * One simulated user session. Holds the stable identity fields reused across
 * every journey action fired within the session.
 */
public final class Session {

    public final String sessnTknId;
    public final String clntIpAddr;
    public final String usrId;        // 19-digit numeric STRING
    public final long usrRltnshpNo;   // 11-digit customer relationship number
    public final String cif;          // 17-char zero-padded CIF derived from relationship no

    public Session() {
        this.sessnTknId = IdGen.tokenId();
        this.clntIpAddr = freshTenIp();
        this.usrId = nineteenDigits();
        this.usrRltnshpNo = elevenDigitRltnshp();
        this.cif = String.format("%017d", this.usrRltnshpNo);
    }

    private static String freshTenIp() {
        ThreadLocalRandom r = ThreadLocalRandom.current();
        return "10." + r.nextInt(1, 255) + "." + r.nextInt(0, 255) + "." + r.nextInt(1, 255);
    }

    private static String nineteenDigits() {
        // First digit 1..9, then 18 more digits -> 19-digit numeric string.
        ThreadLocalRandom r = ThreadLocalRandom.current();
        StringBuilder sb = new StringBuilder(19);
        sb.append(r.nextInt(1, 10));
        for (int i = 0; i < 18; i++) {
            sb.append(r.nextInt(0, 10));
        }
        return sb.toString();
    }

    private static long elevenDigitRltnshp() {
        // 850xxxxxxxx style, 11 digits total.
        return 85_000_000_000L + ThreadLocalRandom.current().nextLong(0, 9_999_999L);
    }
}
