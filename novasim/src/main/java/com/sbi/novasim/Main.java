package com.sbi.novasim;

import com.mongodb.client.MongoClient;
import com.mongodb.client.MongoClients;
import com.mongodb.client.MongoCollection;
import com.mongodb.client.model.Filters;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.apache.logging.log4j.LogManager;
import org.bson.Document;

import picocli.CommandLine;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

/**
 * Entry point for the NOVA 2.0 simulator.
 *
 * <p>Headless: {@code --headless --fire <id> --duration <s>} runs the mesh,
 * fires a scenario, then stops. Otherwise an interactive REPL is started. A
 * background poller watches {@code agent_state._id:"sim:command"} and fires the
 * named scenario when it changes (acking by deleting the command).
 */
@Command(name = "novasim", mixinStandardHelpOptions = true, version = "novasim 2.0",
        description = "Simulates the NOVA 2.0 journey mesh and writes audit documents to Atlas.")
public final class Main implements Callable<Integer> {

    @Option(names = "--rate", description = "background journey-actions/sec (default 5)")
    double rate = 5;

    @Option(names = "--sessions", description = "session pool size (default 40)")
    int sessions = 40;

    @Option(names = "--headless", description = "run without the interactive REPL")
    boolean headless;

    @Option(names = "--fire", description = "scenario id to fire on startup")
    String fire;

    @Option(names = "--duration", description = "headless run duration in seconds (default 30)")
    int duration = 30;

    private SessionPool pool;
    private ScenarioEngine scenarioEngine;
    private JourneyEngine engine;
    private ScheduledExecutorService poller;
    private MongoClient pollClient;

    public static void main(String[] args) {
        int code = new CommandLine(new Main()).execute(args);
        System.exit(code);
    }

    @Override
    public Integer call() {
        pool = new SessionPool(sessions);
        scenarioEngine = new ScenarioEngine();
        engine = new JourneyEngine(pool, scenarioEngine, rate);
        scenarioEngine.bind(engine);
        engine.start();
        startPoller();

        System.err.println("[novasim] started: sessions=" + sessions + " rate=" + rate
                + (headless ? " (headless)" : " (interactive)"));

        if (headless) {
            return runHeadless();
        }
        return runRepl();
    }

    private Integer runHeadless() {
        if (fire != null && !fire.isBlank()) {
            try {
                scenarioEngine.fire(fire, 1, 0);
                System.err.println("[novasim] fired scenario '" + fire + "'");
            } catch (RuntimeException e) {
                System.err.println("[novasim] cannot fire '" + fire + "': " + e.getMessage());
            }
        }
        long endAt = System.currentTimeMillis() + duration * 1000L;
        while (System.currentTimeMillis() < endAt) {
            printStatus();
            sleep(2000);
        }
        shutdown();
        return 0;
    }

    private Integer runRepl() {
        printHelp();
        try (BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            if (fire != null && !fire.isBlank()) {
                scenarioEngine.fire(fire, 1, 0);
                System.out.println("fired '" + fire + "'");
            }
            String line;
            while (true) {
                System.out.print("nova> ");
                System.out.flush();
                line = in.readLine();
                if (line == null) {
                    break;
                }
                String cmd = line.strip();
                if (cmd.isEmpty()) {
                    continue;
                }
                if (!dispatch(cmd)) {
                    break;
                }
            }
        } catch (Exception e) {
            System.err.println("[novasim] repl error: " + e.getMessage());
        }
        shutdown();
        return 0;
    }

    private boolean dispatch(String cmd) {
        String[] parts = cmd.split("\\s+");
        switch (parts[0]) {
            case "status" -> printStatus();
            case "scenarios" -> listScenarios();
            case "rate" -> {
                if (parts.length >= 2) {
                    try {
                        engine.setRate(Double.parseDouble(parts[1]));
                        System.out.println("rate -> " + engine.rate() + "/s");
                    } catch (NumberFormatException e) {
                        System.out.println("usage: rate <number>");
                    }
                } else {
                    System.out.println("rate is " + engine.rate() + "/s");
                }
            }
            case "quiet" -> {
                Mirror.on = false;
                System.out.println("console mirror OFF");
            }
            case "loud" -> {
                Mirror.on = true;
                System.out.println("console mirror ON");
            }
            case "fire" -> fireCommand(parts);
            case "quit", "exit" -> {
                return false;
            }
            default -> System.out.println("unknown command: " + parts[0] + " (try 'scenarios' or 'status')");
        }
        return true;
    }

    private void fireCommand(String[] parts) {
        if (parts.length < 2) {
            System.out.println("usage: fire <id> [--burst n] [--delay Xs]");
            return;
        }
        String id = parts[1];
        int burst = 1;
        long delayMs = 0;
        for (int i = 2; i < parts.length; i++) {
            if ("--burst".equals(parts[i]) && i + 1 < parts.length) {
                burst = Integer.parseInt(parts[++i]);
            } else if ("--delay".equals(parts[i]) && i + 1 < parts.length) {
                delayMs = parseDelay(parts[++i]);
            }
        }
        try {
            scenarioEngine.fire(id, burst, delayMs);
            System.out.println("fired '" + id + "' (burst=" + burst + ", delay=" + delayMs + "ms)");
        } catch (RuntimeException e) {
            System.out.println("cannot fire '" + id + "': " + e.getMessage());
        }
    }

    private static long parseDelay(String s) {
        String t = s.trim().toLowerCase();
        try {
            if (t.endsWith("ms")) {
                return Long.parseLong(t.substring(0, t.length() - 2));
            }
            if (t.endsWith("s")) {
                return (long) (Double.parseDouble(t.substring(0, t.length() - 1)) * 1000);
            }
            return Long.parseLong(t);
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    private void listScenarios() {
        System.out.println("injectable scenarios:");
        for (String id : ScenarioEngine.SCENARIO_IDS) {
            String note = "";
            try {
                Scenario sc = scenarioEngine.load(id);
                note = sc.presenterNote == null ? "" : sc.presenterNote;
            } catch (RuntimeException e) {
                note = "(load error: " + e.getMessage() + ")";
            }
            System.out.printf("  %-32s %s%n", id, note);
        }
    }

    private void printStatus() {
        System.out.printf(
                "[nova-ops] txn=%d err=%d svc=%d | rate=%.1f/s sessions=%d | active-effects=%d last-fire=%s%n",
                engine.txnCount(), engine.errCount(), engine.svcCount(), engine.rate(),
                pool.size(), scenarioEngine.activeCount(), scenarioEngine.lastFired());
    }

    private void printHelp() {
        System.out.println("novasim interactive — commands:");
        System.out.println("  status                       ops snapshot");
        System.out.println("  scenarios                    list injectable failures");
        System.out.println("  fire <id> [--burst n] [--delay Xs]   inject a scenario");
        System.out.println("  rate <n>                     set background actions/sec");
        System.out.println("  quiet | loud                 console mirror off/on");
        System.out.println("  quit                         stop and exit");
    }

    // ---- agent_state poller ------------------------------------------------

    private void startPoller() {
        try {
            String uri = Dotenv.require("MONGODB_URI");
            String dbName = Dotenv.get("MONGODB_DB", "nova_rca");
            pollClient = MongoClients.create(uri);
            MongoCollection<Document> state =
                    pollClient.getDatabase(dbName).getCollection("agent_state");
            poller = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "nova-cmd-poller");
                t.setDaemon(true);
                return t;
            });
            final long[] lastTs = {0L};
            poller.scheduleWithFixedDelay(() -> pollOnce(state, lastTs), 2, 2, TimeUnit.SECONDS);
        } catch (RuntimeException e) {
            System.err.println("[novasim] command poller disabled: " + e.getMessage());
        }
    }

    private void pollOnce(MongoCollection<Document> state, long[] lastTs) {
        try {
            Document doc = state.find(Filters.eq("_id", "sim:command")).first();
            if (doc == null) {
                return;
            }
            String scenario = doc.getString("scenario");
            long ts = extractTs(doc.get("ts"));
            if (scenario == null || scenario.isBlank()) {
                return;
            }
            if (ts != 0 && ts == lastTs[0]) {
                return; // already handled
            }
            lastTs[0] = ts;
            System.err.println("[novasim] poller: firing '" + scenario + "' from agent_state");
            try {
                scenarioEngine.fire(scenario, 1, 0);
            } catch (RuntimeException e) {
                System.err.println("[novasim] poller fire error: " + e.getMessage());
            }
            // ack by deleting the command
            state.deleteOne(Filters.eq("_id", "sim:command"));
        } catch (RuntimeException e) {
            System.err.println("[novasim] poller error: " + e.getMessage());
        }
    }

    private static long extractTs(Object ts) {
        if (ts instanceof java.util.Date d) {
            return d.getTime();
        }
        if (ts instanceof Number n) {
            return n.longValue();
        }
        if (ts instanceof String s) {
            try {
                return java.time.Instant.parse(s).toEpochMilli();
            } catch (RuntimeException ignore) {
                return s.hashCode();
            }
        }
        return 0;
    }

    private void shutdown() {
        System.err.println("[novasim] shutting down...");
        try {
            if (engine != null) {
                engine.stop();
            }
            if (scenarioEngine != null) {
                scenarioEngine.shutdown();
            }
            if (poller != null) {
                poller.shutdownNow();
            }
            if (pollClient != null) {
                pollClient.close();
            }
            // Give the async buffer a moment, then flush + close the Mongo appender.
            sleep(600);
            LogManager.shutdown();
        } catch (RuntimeException e) {
            System.err.println("[novasim] shutdown error: " + e.getMessage());
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
