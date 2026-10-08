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

    public static void main(String[] args) throws Exception {
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
