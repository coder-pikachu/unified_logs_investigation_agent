package com.sbi.novasim;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

/**
 * A fixed pool of ~N user sessions the JourneyEngine draws from. Sessions
 * occasionally rotate so token ids don't stay constant forever.
 */
public final class SessionPool {

    private final List<Session> sessions;

    public SessionPool(int size) {
        this.sessions = new ArrayList<>(size);
        for (int i = 0; i < size; i++) {
            sessions.add(new Session());
        }
    }

    public int size() {
        return sessions.size();
    }

    public Session random() {
        return sessions.get(ThreadLocalRandom.current().nextInt(sessions.size()));
    }

    /** A stable snapshot for scenarios that must touch "many sessions" / a cohort. */
    public List<Session> all() {
        return List.copyOf(sessions);
    }

    /** Pick {@code n} distinct sessions (or all, if n exceeds the pool). */
    public List<Session> sample(int n) {
        List<Session> copy = new ArrayList<>(sessions);
        java.util.Collections.shuffle(copy, ThreadLocalRandom.current());
        return copy.subList(0, Math.min(n, copy.size()));
    }
}
