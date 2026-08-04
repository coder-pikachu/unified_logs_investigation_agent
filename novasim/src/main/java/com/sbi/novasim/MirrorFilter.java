package com.sbi.novasim;

import org.apache.logging.log4j.core.Core;
import org.apache.logging.log4j.core.Filter;
import org.apache.logging.log4j.core.LogEvent;
import org.apache.logging.log4j.core.Logger;
import org.apache.logging.log4j.core.config.plugins.Plugin;
import org.apache.logging.log4j.core.config.plugins.PluginFactory;
import org.apache.logging.log4j.core.filter.AbstractFilter;
import org.apache.logging.log4j.message.Message;

/**
 * Passes events only while {@link Mirror#on} is true. Used to gate the
 * human-readable ConsoleAppender at runtime without touching Atlas output.
 */
@Plugin(name = "MirrorFilter", category = Core.CATEGORY_NAME, elementType = Filter.ELEMENT_TYPE,
        printObject = true)
public final class MirrorFilter extends AbstractFilter {

    private MirrorFilter() {
        super(Result.NEUTRAL, Result.DENY);
    }

    @PluginFactory
    public static MirrorFilter createFilter() {
        return new MirrorFilter();
    }

    private Result decide() {
        return Mirror.on ? Result.NEUTRAL : Result.DENY;
    }

    @Override
    public Result filter(LogEvent event) {
        return decide();
    }

    @Override
    public Result filter(Logger logger, org.apache.logging.log4j.Level level,
                         org.apache.logging.log4j.Marker marker, Message msg, Throwable t) {
        return decide();
    }

    @Override
    public Result filter(Logger logger, org.apache.logging.log4j.Level level,
                         org.apache.logging.log4j.Marker marker, Object msg, Throwable t) {
        return decide();
    }

    @Override
    public Result filter(Logger logger, org.apache.logging.log4j.Level level,
                         org.apache.logging.log4j.Marker marker, String msg, Object... params) {
        return decide();
    }
}
