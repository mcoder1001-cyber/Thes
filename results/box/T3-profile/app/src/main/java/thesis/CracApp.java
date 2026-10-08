package thesis;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ConfigurableApplicationContext;

import java.lang.management.CompilationMXBean;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryPoolMXBean;
import java.lang.management.RuntimeMXBean;
import java.util.Random;

/**
 * D1 (results/box/D1-aot-vs-crac): the exp12 app, changed so ONE jar runs on the CRaC JDK 21
 * and on a stock JDK 25. Changes from exp12: the checkpoint call goes through reflection and
 * only when -Dckpt=true; -Dexit_at_ckpt=true exits at the checkpoint point (the AOT-cache
 * training run: start-up + K requests, the same information a CRaC image at depth K holds);
 * FIRST_DONE_EPOCH_NS and CGROUP are printed at the first response so the runner can time
 * launch -> first response from outside and check the quota the process really ran under.
 *
 * T3-T6b grid additions (results/box/T3-profile, all off by default):
 *   -Drewarm=N      after the restore point, N more requests before the measured first one
 *                   (T4: re-warming a restored sandbox while it waits); REWARM_MS is printed
 *   -Duniq=true     after the restore point, print SHA-256 hashes of values that copies restored
 *                   from one image might share (T5): a Random and a SecureRandom made at
 *                   start-up, Math.random(), UUID.randomUUID(), a start-up token, nanoTime
 *   -Dreset.hooks=on  register a CRaC Resource whose afterRestore re-seeds the Random, re-creates
 *                   the SecureRandom and regenerates the token (the snapshot builder's hooks)
 *
 * Original note, Experiment 12: the depth sweep, with REAL snapshots, on the REAL workload.
 *
 * exp11 did CRaC checkpoint/restore but on a light handler (steady 0.35 ms), which
 * put it in exp3's toy regime -- and exp3's toy regime is exactly what gave the wrong
 * answer once before, corrected by exp3b. This runs the same sweep on exp3b's Spring
 * Boot stack (web starter + Jackson + Hibernate Validator, no HTTP server) so the
 * measured depth curve is comparable to the one exp6 DERIVED from warm-up traces.
 *
 * The question: does a snapshot taken after K warm-up requests actually remove the
 * warm-up that exp6's captured(K) model says it removes?
 *
 * Output on stdout:
 *   CHECKPOINT_META  <spring_refresh_ms> <codecache_at_ckpt> <compile_ms_at_ckpt>
 *   POST_RESTORE_CURVE                      then "<i>,<nanos>" per line
 *   FIRST_AFTER_RESTORE_MS <ms>
 *   STEADY_MS <ms>
 *
 * The post-restore curve is the point: it lets R_measured(K) = sum (l_i - C)+ be
 * computed from a real restore, and set against R_derived(K) from exp6/exp8.
 */
@SpringBootApplication
public class CracApp {

    static final int WARM = Integer.getInteger("warm", 0);
    static final int POST = Integer.getInteger("post", 400);
    static final int ORDERS = Integer.getInteger("orders", 400);

    static long codeCache() {
        long t = 0;
        for (MemoryPoolMXBean p : ManagementFactory.getMemoryPoolMXBeans()) {
            if (p.getName().toLowerCase().contains("code")) t += p.getUsage().getUsed();
        }
        return t;
    }

    /** Identical payload generation to exp3b, so the workloads are comparable. */
    static String payload() {
        Random rnd = new Random(42);
        String[] regions = {"emea", "apac", "amer", "latam"};
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < ORDERS; i++) {
            if (i > 0) sb.append(',');
            sb.append("{\"id\":\"o").append(i)
              .append("\",\"region\":\"").append(regions[rnd.nextInt(regions.length)])
              .append("\",\"qty\":").append(1 + rnd.nextInt(20))
              .append(",\"price\":").append(String.format("%.2f", 1 + rnd.nextDouble() * 500))
              .append(",\"note\":\"n").append(i).append("\"}");
        }
        return sb.append(']').toString();
    }

    static java.util.Random startRandom;
    static java.security.SecureRandom startSecure;
    static String startToken;

    static String token(java.security.SecureRandom r) {
        byte[] b = new byte[16];
        r.nextBytes(b);
        return java.util.HexFormat.of().formatHex(b);
    }

    static String sha(String v) throws Exception {
        return java.util.HexFormat.of().formatHex(
                java.security.MessageDigest.getInstance("SHA-256").digest(v.getBytes()));
    }

    /** The builder's reset hook, as a jdk.crac.Resource made by reflection (no compile-time CRaC). */
    static Object resetHook;

    static void registerResetHook() throws Exception {
        Class<?> res = Class.forName("jdk.crac.Resource");
        resetHook = java.lang.reflect.Proxy.newProxyInstance(CracApp.class.getClassLoader(), new Class<?>[]{res},
                (proxy, m, a) -> {
                    switch (m.getName()) {       // a Proxy must answer Object's methods itself
                        case "hashCode": return System.identityHashCode(proxy);
                        case "equals": return proxy == a[0];
                        case "toString": return "resetHook";
                        default: break;
                    }
                    if (m.getName().equals("afterRestore")) {
                        startRandom = new java.util.Random();
                        startSecure = new java.security.SecureRandom();
                        startToken = token(startSecure);
                    }
                    return null;
                });
        Object ctx = Class.forName("jdk.crac.Core").getMethod("getGlobalContext").invoke(null);
        Class.forName("jdk.crac.Context").getMethod("register", res).invoke(ctx, resetHook);
    }

    public static void main(String[] args) throws Exception {
        boolean uniq = Boolean.getBoolean("uniq");
        if (uniq) {                       // everything a function might create at start-up
            startRandom = new java.util.Random();
            startSecure = new java.security.SecureRandom();
            startToken = token(startSecure);
            Math.random();                // initialise Math.random's generator before the checkpoint
            java.util.UUID.randomUUID();  // and UUID's SecureRandom holder
            if ("on".equals(System.getProperty("reset.hooks"))) registerResetHook();
        }
        RuntimeMXBean rt = ManagementFactory.getRuntimeMXBean();
        CompilationMXBean comp = ManagementFactory.getCompilationMXBean();

        long beforeSpring = rt.getUptime();
        ConfigurableApplicationContext ctx =
                new SpringApplication(CracApp.class).run(args);     // cost A
        long springMs = rt.getUptime() - beforeSpring;

        OrderService svc = ctx.getBean(OrderService.class);
        String json = payload();

        long sink = 0;
        for (int i = 0; i < WARM; i++) sink += svc.handle(json).length();  // K warm-up requests

        System.out.printf("CHECKPOINT_META %d %d %d%n", springMs, codeCache(),
                comp.isCompilationTimeMonitoringSupported() ? comp.getTotalCompilationTime() : -1);
        System.out.flush();

        // ---- checkpoint. On restore, execution resumes right here. ----------
        if (Boolean.getBoolean("exit_at_ckpt")) System.exit(0);
        if (Boolean.getBoolean("ckpt")) {
            try {
                Class.forName("jdk.crac.Core").getMethod("checkpointRestore").invoke(null);
            } catch (Throwable t) {
                System.out.println("CHECKPOINT_THREW " + t);
                System.out.flush();
            }
        }

        // ---- everything below runs in the RESTORED process -------------------
        if (uniq) {
            System.out.println("UNIQ random " + sha(Long.toString(startRandom.nextLong())));
            System.out.println("UNIQ math_random " + sha(Double.toString(Math.random())));
            System.out.println("UNIQ uuid " + sha(java.util.UUID.randomUUID().toString()));
            System.out.println("UNIQ secure_random " + sha(token(startSecure)));
            System.out.println("UNIQ token " + sha(startToken));
            System.out.println("UNIQ nanotime " + sha(Long.toString(System.nanoTime())));
        }
        int rewarm = Integer.getInteger("rewarm", 0);
        if (rewarm > 0) {
            long r0 = System.nanoTime();
            for (int i = 0; i < rewarm; i++) sink += svc.handle(json).length();
            System.out.printf("REWARM_MS %.3f%n", (System.nanoTime() - r0) / 1e6);
        }
        long t0 = System.nanoTime();
        sink += svc.handle(json).length();
        java.time.Instant now = java.time.Instant.now();
        System.out.printf("FIRST_AFTER_RESTORE_MS %.4f%n", (System.nanoTime() - t0) / 1e6);
        System.out.println("FIRST_DONE_EPOCH_NS " + (now.getEpochSecond() * 1_000_000_000L + now.getNano()));
        try {
            System.out.println("CGROUP " + new String(java.nio.file.Files.readAllBytes(
                    java.nio.file.Path.of("/proc/self/cgroup"))).trim());
        } catch (Exception e) { System.out.println("CGROUP ?"); }

        System.out.println("POST_RESTORE_CURVE");
        long[] ns = new long[POST];
        for (int i = 0; i < POST; i++) {
            long s = System.nanoTime();
            sink += svc.handle(json).length();
            ns[i] = System.nanoTime() - s;
        }
        for (int i = 0; i < POST; i++) System.out.printf("%d,%d%n", i, ns[i]);

        long best = Long.MAX_VALUE;
        for (long v : ns) if (v < best) best = v;
        System.out.printf("STEADY_MS %.4f%n", best / 1e6);
        System.out.printf("RESTORE_META %d %d sink=%d%n", codeCache(),
                comp.isCompilationTimeMonitoringSupported() ? comp.getTotalCompilationTime() : -1,
                sink);
        System.out.flush();
        System.exit(0);
    }
}
