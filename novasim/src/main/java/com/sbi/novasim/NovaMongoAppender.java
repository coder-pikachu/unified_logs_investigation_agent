package com.sbi.novasim;

import com.mongodb.MongoException;
import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.MongoDatabase;
import com.mongodb.client.model.InsertManyOptions;

import java.io.Serializable;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

import org.apache.logging.log4j.core.Appender;
import org.apache.logging.log4j.core.Core;
import org.apache.logging.log4j.core.Filter;
import org.apache.logging.log4j.core.LogEvent;
import org.apache.logging.log4j.core.appender.AbstractAppender;
import org.apache.logging.log4j.core.config.Property;
import org.apache.logging.log4j.core.config.plugins.Plugin;
import org.apache.logging.log4j.core.config.plugins.PluginAttribute;
import org.apache.logging.log4j.core.config.plugins.PluginElement;
import org.apache.logging.log4j.core.config.plugins.PluginFactory;
import org.apache.logging.log4j.message.MapMessage;
import org.apache.logging.log4j.message.Message;
import org.bson.Document;

/**
 * Custom Log4j2 appender that turns {@link MapMessage} events into BSON
 * documents and batch-inserts them into Atlas.
 *
 * <p>Contract: each MapMessage carries a {@code _collection} key naming the
 * target collection. Meta keys (any key starting with {@code _}) are stripped;
 * remaining fields become a {@link Document}. ISO instant strings on the date
 * keys ({@code strt_time,end_time,crtd_on,err_time}) are parsed to
 * {@link Date}; {@code usr_id} stays a String; ints stay ints.
 *
 * <p>Inserts flush at 100 docs OR every 200ms. The queue is a bounded
 * {@link ArrayBlockingQueue}(10000) with drop-oldest overflow. Insert failures
 * retry with exponential backoff. {@link #append(LogEvent)} NEVER throws.
 */
@Plugin(name = "NovaMongo", category = Core.CATEGORY_NAME, elementType = Appender.ELEMENT_TYPE,
        printObject = true)
public final class NovaMongoAppender extends AbstractAppender {

    /** Date-typed keys: ISO instant strings are parsed into {@link Date}. */
    private static final Set<String> DATE_KEYS = Set.of("strt_time", "end_time", "crtd_on", "err_time");
    /** Kept as String even though it looks numeric. */
    private static final Set<String> STRING_KEYS = Set.of("usr_id");

    private static final int QUEUE_CAPACITY = 10_000;
    private static final int FLUSH_AT = 100;
    private static final long FLUSH_MS = 200L;
    private static final int MAX_RETRIES = 5;

    private final ArrayBlockingQueue<Document> queue = new ArrayBlockingQueue<>(QUEUE_CAPACITY);
    private final AtomicBoolean started = new AtomicBoolean(false);
    private final AtomicLong dropped = new AtomicLong(0);

    private final ConcurrentHashMap<String, MongoCollection<Document>> collections =
            new ConcurrentHashMap<>();

    private volatile MongoClient client;
    private volatile MongoDatabase db;
    private ScheduledExecutorService flusher;

    private NovaMongoAppender(String name, Filter filter) {
        super(name, filter, null, true, Property.EMPTY_ARRAY);
    }

    @PluginFactory
    public static NovaMongoAppender createAppender(
            @PluginAttribute("name") String name,
            @PluginElement("Filter") Filter filter) {
        if (name == null) {
            name = "NovaMongo";
        }
        return new NovaMongoAppender(name, filter);
    }

    @Override
    public void start() {
        super.start();
        try {
            String uri = Dotenv.require("MONGODB_URI");
            String dbName = Dotenv.get("MONGODB_DB", "nova_rca");
            this.client = MongoClients.create(uri);
            this.db = client.getDatabase(dbName);
            this.flusher = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "nova-mongo-flusher");
                t.setDaemon(true);
                return t;
            });
            this.flusher.scheduleWithFixedDelay(this::drainAndFlush, FLUSH_MS, FLUSH_MS,
                    TimeUnit.MILLISECONDS);
            started.set(true);
            System.err.println("[novasim] NovaMongoAppender connected to db '" + dbName + "'");
        } catch (RuntimeException e) {
            System.err.println("[novasim] NovaMongoAppender failed to start: " + e.getMessage());
        }
    }

    @Override
    public void append(LogEvent event) {
        try {
            if (!started.get()) {
                return;
            }
            Message msg = event.getMessage();
            if (!(msg instanceof MapMessage<?, ?> mm)) {
                return;
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> data = ((MapMessage<?, Object>) mm).getData();
            String collection = asString(data.get("_collection"));
            if (collection == null || collection.isBlank()) {
                return;
            }
            Document doc = toDocument(data);
            offerDropOldest(doc.append("__col", collection));
        } catch (RuntimeException e) {
            // NEVER propagate out of append().
            System.err.println("[novasim] append() swallowed: " + e.getMessage());
        }
    }

    /** Bounded queue with drop-oldest semantics + a stderr warning. */
    private void offerDropOldest(Document doc) {
        while (!queue.offer(doc)) {
            Document evicted = queue.poll();
            if (evicted != null) {
                long n = dropped.incrementAndGet();
                if (n % 100 == 1) {
                    System.err.println("[novasim] WARN mongo queue full; dropped oldest doc (total dropped="
                            + n + ")");
                }
            }
        }
    }

    private void drainAndFlush() {
        try {
            if (queue.isEmpty()) {
                return;
            }
            List<Document> batch = new ArrayList<>(FLUSH_AT);
            queue.drainTo(batch);
            if (batch.isEmpty()) {
                return;
            }
            // Group by collection (they share one appender / one queue).
            ConcurrentHashMap<String, List<Document>> byCol = new ConcurrentHashMap<>();
            for (Document d : batch) {
                String col = (String) d.remove("__col");
                byCol.computeIfAbsent(col, k -> new ArrayList<>()).add(d);
            }
            byCol.forEach(this::insertWithRetry);
        } catch (RuntimeException e) {
            System.err.println("[novasim] flush error: " + e.getMessage());
        }
    }

    private void insertWithRetry(String collection, List<Document> docs) {
        MongoCollection<Document> col =
                collections.computeIfAbsent(collection, c -> db.getCollection(c));
        InsertManyOptions opts = new InsertManyOptions().ordered(false);
        long backoff = 50L;
        for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
            try {
                col.insertMany(docs, opts);
                return;
            } catch (MongoException e) {
                if (attempt == MAX_RETRIES) {
                    System.err.println("[novasim] insert to '" + collection + "' failed after "
                            + MAX_RETRIES + " attempts: " + e.getMessage());
                    return;
                }
                try {
                    Thread.sleep(backoff);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
                backoff = Math.min(backoff * 2, 2_000L);
            }
        }
    }

    /** Convert stripped MapMessage data into a typed BSON document. */
    private static Document toDocument(Map<String, Object> data) {
        Document doc = new Document();
        for (Map.Entry<String, Object> e : data.entrySet()) {
            String key = e.getKey();
            if (key.startsWith("_")) {
                continue; // meta key
            }
            Object val = e.getValue();
            if (val == null) {
                doc.append(key, null);
                continue;
            }
            if (STRING_KEYS.contains(key)) {
                doc.append(key, asString(val));
            } else if (DATE_KEYS.contains(key)) {
                doc.append(key, toDate(val));
            } else {
                doc.append(key, coerce(val));
            }
        }
        return doc;
    }

    /** Parse ISO instant strings into Date; pass through existing Dates. */
    private static Object toDate(Object val) {
        if (val instanceof Date d) {
            return d;
        }
        String s = asString(val);
        if (s == null) {
            return null;
        }
        try {
            return Date.from(Instant.parse(s));
        } catch (DateTimeParseException e) {
            return s; // leave as-is rather than lose data
        }
    }

    /** Preserve native scalar types; convert nested Maps/Lists into BSON structures. */
    private static Object coerce(Object val) {
        if (val instanceof Map<?, ?> map) {
            Document sub = new Document();
            for (Map.Entry<?, ?> e : map.entrySet()) {
                Object v = e.getValue();
                sub.append(String.valueOf(e.getKey()), v == null ? null : coerce(v));
            }
            return sub;
        }
        if (val instanceof List<?> list) {
            List<Object> out = new ArrayList<>(list.size());
            for (Object v : list) {
                out.add(v == null ? null : coerce(v));
            }
            return out;
        }
        // Integer/Long/Double/Boolean and Strings (incl. JSON payloads, "NULL") pass through.
        return val;
    }

    private static String asString(Object o) {
        return o == null ? null : o.toString();
    }

    @Override
    public boolean stop(long timeout, TimeUnit timeUnit) {
        setStopping();
        started.set(false);
        try {
            if (flusher != null) {
                flusher.shutdown();
            }
            drainAndFlush(); // best-effort final flush
        } catch (RuntimeException e) {
            System.err.println("[novasim] stop flush error: " + e.getMessage());
        } finally {
            if (client != null) {
                try {
                    client.close();
                } catch (RuntimeException ignore) {
                    // closing best-effort
                }
            }
        }
        boolean s = super.stop(timeout, timeUnit);
        setStopped();
        return s;
    }

    @Override
    public String toString() {
        return "NovaMongoAppender{queue=" + queue.size() + ",dropped=" + dropped.get() + "}";
    }
}
