package com.sbi.novasim;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.Map;

/** Small JSON helpers built on a shared Jackson mapper. */
public final class Json {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private Json() {
    }

    /** Serialize to a compact-ish JSON string (spaces after separators, like the sample). */
    public static String str(Object value) {
        try {
            return MAPPER.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            return "{}";
        }
    }

    /**
     * Double-encode: wrap {@code inner} (already an object) as a JSON string value
     * under {@code wrapperKey}, i.e. JSON-inside-a-JSON-string, mirroring the
     * observed {@code {"response":"{\"totalMsgs\":0}"}} shape.
     */
    public static String doubleEncoded(String wrapperKey, Object inner) {
        Map<String, Object> outer = new LinkedHashMap<>();
        outer.put(wrapperKey, str(inner));
        return str(outer);
    }

    public static Map<String, Object> map() {
        return new LinkedHashMap<>();
    }
}
