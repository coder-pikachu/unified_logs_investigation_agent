package com.sbi.novasim;

/**
 * Global toggle for the human-readable console mirror. When {@code on} is true
 * the ConsoleAppender in log4j2.xml echoes a legible line per emitted document;
 * console output is NEVER written to Atlas.
 */
public final class Mirror {

    /** Default quiet: the interactive status line owns the console. */
    public static volatile boolean on = false;

    private Mirror() {
    }
}
