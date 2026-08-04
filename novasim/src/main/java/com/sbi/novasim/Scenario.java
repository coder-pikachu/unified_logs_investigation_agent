package com.sbi.novasim;

import java.util.List;
import java.util.Map;

/**
 * Data-only scenario definition, deserialized from
 * {@code resources/scenarios/<id>.json}. Effects are interpreted by generic
 * handlers in {@link ScenarioEngine}; there is NO scenario-specific code.
 */
public final class Scenario {

    public String id;
    public String presenterNote;
    public int durationSeconds;
    public List<Effect> effects;

    /** One timed effect. {@code params} is interpreted per {@code kind}. */
    public static final class Effect {
        public int atOffsetMs;
        public String kind;
        public Map<String, Object> params;
    }
}
