package com.sbi.novasim;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

/**
 * Tiny dotenv reader. Resolves a key from the process environment first; if
 * absent, parses the repo-root {@code .env} (searching upward from the working
 * directory). No external dependency, tolerant of comments and quotes.
 */
public final class Dotenv {

    private static final Map<String, String> FILE = load();

    private Dotenv() {
    }

    /** The repo-root {@code .env} is authoritative; fall back to the process env. */
    public static String get(String key, String def) {
        String v = FILE.get(key);
        if (v == null || v.isBlank()) {
            v = System.getenv(key);
        }
        return (v == null || v.isBlank()) ? def : v;
    }

    public static String require(String key) {
        String v = get(key, null);
        if (v == null) {
            throw new IllegalStateException("Required environment variable " + key
                    + " is not set (checked env and repo-root .env)");
        }
        return v;
    }

    private static Map<String, String> load() {
        Map<String, String> out = new HashMap<>();
        Path env = findEnv();
        if (env == null) {
            return out;
        }
        try (BufferedReader r = Files.newBufferedReader(env, StandardCharsets.UTF_8)) {
            String line;
            while ((line = r.readLine()) != null) {
                String s = line.strip();
                if (s.isEmpty() || s.startsWith("#")) {
                    continue;
                }
                if (s.startsWith("export ")) {
                    s = s.substring("export ".length()).strip();
                }
                int eq = s.indexOf('=');
                if (eq <= 0) {
                    continue;
                }
                String k = s.substring(0, eq).strip();
                String val = s.substring(eq + 1).strip();
                if (val.length() >= 2
                        && ((val.charAt(0) == '"' && val.charAt(val.length() - 1) == '"')
                        || (val.charAt(0) == '\'' && val.charAt(val.length() - 1) == '\''))) {
                    val = val.substring(1, val.length() - 1);
                }
                out.put(k, val);
            }
        } catch (IOException e) {
            System.err.println("[novasim] warning: could not read .env: " + e.getMessage());
        }
        return out;
    }

    /** Walk up from CWD (and this jar's dir) looking for a {@code .env}. */
    private static Path findEnv() {
        Path dir = Paths.get("").toAbsolutePath();
        for (int i = 0; i < 6 && dir != null; i++) {
            Path candidate = dir.resolve(".env");
            if (Files.isRegularFile(candidate)) {
                return candidate;
            }
            // also try ../.env explicitly (novasim/ sits one below repo root)
            Path parentEnv = dir.getParent() == null ? null : dir.getParent().resolve(".env");
            if (parentEnv != null && Files.isRegularFile(parentEnv)) {
                return parentEnv;
            }
            dir = dir.getParent();
        }
        return null;
    }
}
