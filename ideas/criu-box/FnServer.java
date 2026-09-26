// FnServer.java -- the exp-a stage (Fn.handle) behind a tiny HTTP server, so it can be
// checkpointed and restored with raw CRIU (or CRaC) on the S0 box. OpenWhisk's action
// proxy has the same shape: a process listening on a port, fed one request at a time.
//
//   GET  /ping                      -> "ok"                      (readiness probe)
//   POST /run            body=JSON  -> handler output; header X-Handler-Us
//   GET  /prime?file=F&n=N          -> runs the first N lines of F; "<ms>"  (priming / re-warming)
//   GET  /jit                       -> "<total JIT ms>"          (CompilationMXBean)
//
// Build (from ideas/):  javac -d criu-box/build -cp "exp-a-context-priming/lib/*" \
//                         exp-a-context-priming/src/Fn.java criu-box/FnServer.java
// Run:                  java -XX:-UsePerfData -XX:+UseSerialGC -Xms256m -Xmx256m \
//                         -cp "criu-box/build:exp-a-context-priming/lib/*" FnServer 8080

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.lang.management.ManagementFactory;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;

public class FnServer {
    static void reply(HttpExchange ex, int code, String body, long handlerUs) throws IOException {
        byte[] b = body.getBytes(StandardCharsets.UTF_8);
        if (handlerUs >= 0) ex.getResponseHeaders().add("X-Handler-Us", Long.toString(handlerUs));
        ex.sendResponseHeaders(code, b.length);
        try (OutputStream o = ex.getResponseBody()) { o.write(b); }
    }

    static Map<String, String> query(HttpExchange ex) {
        Map<String, String> m = new HashMap<>();
        String q = ex.getRequestURI().getRawQuery();
        if (q != null) for (String kv : q.split("&")) {
            int i = kv.indexOf('=');
            if (i > 0) m.put(kv.substring(0, i), java.net.URLDecoder.decode(kv.substring(i + 1), StandardCharsets.UTF_8));
        }
        return m;
    }

    public static void main(String[] args) throws Exception {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 8080;
        HttpServer s = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 64);
        s.setExecutor(Executors.newSingleThreadExecutor());   // one request at a time, like OpenWhisk
        s.createContext("/ping", ex -> reply(ex, 200, "ok", -1));
        s.createContext("/run", ex -> {
            String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            try {
                long t0 = System.nanoTime();
                String out = Fn.handle(body);
                reply(ex, 200, out, (System.nanoTime() - t0) / 1000);
            } catch (Exception e) {
                reply(ex, 500, e.toString(), -1);
            }
        });
        s.createContext("/prime", ex -> {
            Map<String, String> q = query(ex);
            long n = Long.parseLong(q.getOrDefault("n", "100"));
            try {
                List<String> reqs;
                try (var lines = Files.lines(Path.of(q.get("file")))) { reqs = lines.limit(n).toList(); }
                long t0 = System.nanoTime();
                for (String r : reqs) Fn.handle(r);
                reply(ex, 200, Long.toString((System.nanoTime() - t0) / 1_000_000), -1);
            } catch (Exception e) {
                reply(ex, 500, e.toString(), -1);
            }
        });
        s.createContext("/jit", ex -> reply(ex, 200,
                Long.toString(ManagementFactory.getCompilationMXBean().getTotalCompilationTime()), -1));
        s.start();
        System.out.println("listening " + port);
    }
}
