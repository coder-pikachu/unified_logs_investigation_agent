package com.sbi.novasim;

import java.util.Map;

import org.apache.logging.log4j.message.MapMessage;

/**
 * A {@link MapMessage} with Object-typed values so ints, Dates and JSON strings
 * survive intact on their way to {@link NovaMongoAppender}. Keys starting with
 * {@code _} are meta (e.g. {@code _collection}) and stripped by the appender.
 */
public final class DocMessage extends MapMessage<DocMessage, Object> {

    public DocMessage(Map<String, Object> data) {
        super(data);
    }
}
