// Sig.java -- the control-flow signature of Fn.handle() for each request.
//
// Proposition 7 of theory/DAG_SNAPSHOT_THEORY.md: if a scrubbing map phi preserves every
// predicate the handler branches on, then x and phi(x) execute the same path, so priming on
// phi(X) produces the same JIT profile as priming on X. This program makes "the same path"
// checkable: it evaluates, per request, every predicate Fn.handle() branches on (dispatch
// type, regex outcomes, numeric thresholds, null checks, loop trip counts) and prints them as
// one line. Comparing the lines of X and phi(X) measures exactly which predicates phi keeps.
//
// It mirrors Fn.handle() by hand, so it must be updated if handle() changes.
// usage: java -cp build:lib/* Sig <file.jsonl> [n]   -> one signature per line on stdout

import java.io.BufferedWriter;
import java.io.OutputStreamWriter;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public class Sig {
    static String sig(String json) throws Exception {
        Fn.Order o = Fn.M.readValue(json, Fn.Order.class);
        StringBuilder sb = new StringBuilder();
        String country = o.ship != null ? o.ship.country : "US";
        boolean warn = false;
        // order-level predicates, in the order handle() evaluates them
        boolean hasEmail = o.customer != null && o.customer.email != null;
        boolean emailOk = hasEmail && Fn.EMAIL.matcher(o.customer.email).matches();
        boolean hasZip = o.ship != null && o.ship.zip != null;
        boolean zipOk = hasZip && Fn.ZIP.matcher(o.ship.zip).matches();
        if (hasEmail && !emailOk) warn = true;
        if (hasZip && !zipOk) warn = true;
        sb.append("n=").append(o.items.size())
          .append(";cur=").append("JPY".equals(o.currency) ? "JPY" : "other")
          .append(";US=").append("US".equals(country) ? 1 : 0)
          .append(";email=").append(hasEmail ? (emailOk ? "ok" : "bad") : "none")
          .append(";zip=").append(hasZip ? (zipOk ? "ok" : "bad") : "none");
        // per-item predicates
        BigDecimal subtotal = BigDecimal.ZERO;
        sb.append(";items=");
        for (Fn.Item it : o.items) {
            boolean skuOk = Fn.SKU.matcher(it.sku).matches();
            if (!skuOk) warn = true;
            sb.append(it.getClass().getSimpleName(), 0, 2).append(skuOk ? '+' : '-');
            if (it instanceof Fn.Electronics e) sb.append(e.warrantyMonths > 12 ? 'W' : 'w');
            if (it instanceof Fn.Grocery g) sb.append(g.perishable ? 'P' : 'p');
            if (it instanceof Fn.Digital d) sb.append(d.seats >= 1 ? 'S' : 's');
            subtotal = subtotal.add(it.lineTotal());
        }
        // discount branch
        String disc;
        if (o.coupon != null && o.coupon.startsWith("PCT")) disc = "pct";
        else if (o.customer != null && o.customer.tier >= 3 && subtotal.compareTo(new BigDecimal("500")) > 0) disc = "tier";
        else disc = "none";
        sb.append(";disc=").append(disc)
          .append(";meta=").append(o.meta == null ? "none" : ("high".equals(o.meta.getOrDefault("priority", "normal")) ? "high" : "normal"))
          .append(";warn=").append(warn ? 1 : 0);
        return sb.toString();
    }

    public static void main(String[] a) throws Exception {
        long n = a.length > 1 ? Long.parseLong(a[1]) : Long.MAX_VALUE;
        List<String> reqs;
        try (var lines = Files.lines(Path.of(a[0]))) { reqs = lines.limit(n).toList(); }
        BufferedWriter out = new BufferedWriter(new OutputStreamWriter(System.out));
        for (String r : reqs) { out.write(sig(r)); out.newLine(); }
        out.flush();
    }
}
