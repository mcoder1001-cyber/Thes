// Fn.java -- one stage of an order-processing workflow, driven over stdin.
//
// The stage is reached from two DAG edges that feed it structurally different
// inputs ("web" checkout vs "bulk" import). The question this program exists to
// answer: does a JIT-warmed process primed on one edge's inputs serve the other
// edge's inputs as fast as a process primed on the right edge? If not, a deep
// snapshot must be keyed by DAG context, not just by function.
//
// Protocol (one command per line on stdin, one reply line on stdout):
//   INIT                 build the ObjectMapper and warm the file-read path; "OK <ms>"
//   RUN  <file> <label> [n]  run the first n (default: all) JSON lines of <file>;
//                        "LAT <label> <us>,<us>,..."  (per-request, handler only)
//   SLEEP <ms>           idle (lets queued background compilations finish)
//   QUIT
//
// Latency is System.nanoTime() around handle() only: input is read into memory
// before the timed loop, so file I/O is not in the measurement.

import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

public class Fn {

    // ---------------------------------------------------------------- model
    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, property = "kind")
    @JsonSubTypes({
        @JsonSubTypes.Type(value = Book.class, name = "book"),
        @JsonSubTypes.Type(value = Electronics.class, name = "electronics"),
        @JsonSubTypes.Type(value = Grocery.class, name = "grocery"),
        @JsonSubTypes.Type(value = Subscription.class, name = "subscription"),
        @JsonSubTypes.Type(value = GiftCard.class, name = "giftcard"),
        @JsonSubTypes.Type(value = Digital.class, name = "digital"),
    })
    public abstract static class Item {
        public String sku;
        public String title;
        public int qty;
        public BigDecimal unitPrice;
        abstract BigDecimal taxRate(String country);
        abstract String category();
        BigDecimal lineTotal() { return unitPrice.multiply(BigDecimal.valueOf(qty)); }
    }
    public static class Book extends Item {
        public String isbn; public int pages;
        BigDecimal taxRate(String c) { return "US".equals(c) ? BigDecimal.ZERO : new BigDecimal("0.05"); }
        String category() { return "media"; }
    }
    public static class Electronics extends Item {
        public int warrantyMonths; public String brand;
        BigDecimal taxRate(String c) { return "US".equals(c) ? new BigDecimal("0.0825") : new BigDecimal("0.20"); }
        String category() { return "hardware"; }
        BigDecimal lineTotal() {
            BigDecimal b = super.lineTotal();
            return warrantyMonths > 12 ? b.add(new BigDecimal("9.99").multiply(BigDecimal.valueOf(qty))) : b;
        }
    }
    public static class Grocery extends Item {
        public double weightKg; public boolean perishable; public String origin;
        BigDecimal taxRate(String c) { return perishable ? new BigDecimal("0.07") : new BigDecimal("0.10"); }
        String category() { return perishable ? "fresh" : "pantry"; }
        BigDecimal lineTotal() {
            return unitPrice.multiply(BigDecimal.valueOf(weightKg)).multiply(BigDecimal.valueOf(qty))
                            .setScale(2, RoundingMode.HALF_EVEN);
        }
    }
    public static class Subscription extends Item {
        public int months; public String plan;
        BigDecimal taxRate(String c) { return new BigDecimal("0.19"); }
        String category() { return "recurring"; }
        BigDecimal lineTotal() { return super.lineTotal().multiply(BigDecimal.valueOf(months)); }
    }
    public static class GiftCard extends Item {
        public String recipient;
        BigDecimal taxRate(String c) { return BigDecimal.ZERO; }
        String category() { return "voucher"; }
    }
    public static class Digital extends Item {
        public String licenseKey; public int seats;
        BigDecimal taxRate(String c) { return new BigDecimal("0.15"); }
        String category() { return "software"; }
        BigDecimal lineTotal() { return super.lineTotal().multiply(BigDecimal.valueOf(Math.max(1, seats))); }
    }
    public static class Address { public String street, city, zip, country; }
    public static class Customer { public String id, name, email; public int tier; public List<String> tags; }
    public static class Order {
        public String id, channel, currency, coupon;
        public long createdAt;
        public Customer customer;
        public Address ship;
        public List<Item> items;
        public Map<String, String> meta;
    }
    public static class Result {
        public String orderId, status;
        public BigDecimal subtotal, tax, discount, total;
        public Map<String, BigDecimal> byCategory;
        public List<String> warnings;
        public int lines;
    }

    // -------------------------------------------------------------- handler
    static final ObjectMapper M = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
    static final Pattern SKU = Pattern.compile("^[A-Z]{2,4}-[0-9]{3,8}(-[A-Z0-9]{1,4})?$");
    static final Pattern EMAIL = Pattern.compile("^[\\w.+-]+@[\\w-]+(\\.[\\w-]+)+$");
    static final Pattern ZIP = Pattern.compile("^[0-9A-Z -]{3,10}$");

    static String handle(String json) throws Exception {
        Order o = M.readValue(json, Order.class);
        Result r = new Result();
        r.orderId = o.id;
        r.warnings = new ArrayList<>();
        String country = o.ship != null ? o.ship.country : "US";

        if (o.customer != null && o.customer.email != null && !EMAIL.matcher(o.customer.email).matches())
            r.warnings.add("bad-email");
        if (o.ship != null && o.ship.zip != null && !ZIP.matcher(o.ship.zip).matches())
            r.warnings.add("bad-zip");

        BigDecimal subtotal = BigDecimal.ZERO, tax = BigDecimal.ZERO;
        for (Item it : o.items) {
            if (!SKU.matcher(it.sku).matches()) r.warnings.add("bad-sku:" + it.sku);
            BigDecimal line = it.lineTotal();
            subtotal = subtotal.add(line);
            tax = tax.add(line.multiply(it.taxRate(country)));
        }
        Map<String, BigDecimal> byCat = o.items.stream().collect(Collectors.groupingBy(
                Item::category, TreeMap::new,
                Collectors.reducing(BigDecimal.ZERO, Item::lineTotal, BigDecimal::add)));

        BigDecimal discount = BigDecimal.ZERO;
        if (o.coupon != null && o.coupon.startsWith("PCT")) {
            int pct = Integer.parseInt(o.coupon.substring(3));
            discount = subtotal.multiply(BigDecimal.valueOf(pct)).divide(BigDecimal.valueOf(100), 2, RoundingMode.HALF_UP);
        } else if (o.customer != null && o.customer.tier >= 3 && subtotal.compareTo(new BigDecimal("500")) > 0) {
            discount = subtotal.multiply(new BigDecimal("0.03"));
        }
        int scale = "JPY".equals(o.currency) ? 0 : 2;
        r.subtotal = subtotal.setScale(scale, RoundingMode.HALF_EVEN);
        r.tax = tax.setScale(scale, RoundingMode.HALF_EVEN);
        r.discount = discount.setScale(scale, RoundingMode.HALF_EVEN);
        r.total = r.subtotal.add(r.tax).subtract(r.discount);
        r.byCategory = byCat;
        r.lines = o.items.size();
        if (o.meta != null) {
            String prio = o.meta.getOrDefault("priority", "normal");
            r.status = r.warnings.isEmpty() ? ("high".equals(prio) ? "EXPEDITE" : "OK") : "REVIEW";
        } else {
            r.status = r.warnings.isEmpty() ? "OK" : "REVIEW";
        }
        return M.writeValueAsString(r);
    }

    // ---------------------------------------------------------------- driver
    static volatile int sink;

    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        String line;
        while ((line = in.readLine()) != null) {
            String[] a = line.trim().split("\\s+");
            switch (a[0]) {
                case "INIT" -> {
                    long t0 = System.nanoTime();
                    M.getTypeFactory();                  // framework init: mapper built at class init
                    if (a.length > 1) try (var lines = Files.lines(Path.of(a[1]))) { sink += (int) lines.limit(1).count(); }
                    System.out.println("OK " + (System.nanoTime() - t0) / 1_000_000);
                }
                case "RUN" -> {
                    long n = a.length > 3 ? Long.parseLong(a[3]) : Long.MAX_VALUE;
                    List<String> reqs;
                    try (var lines = Files.lines(Path.of(a[1]))) { reqs = lines.limit(n).toList(); }
                    StringBuilder sb = new StringBuilder("LAT ").append(a[2]).append(' ');
                    for (int i = 0; i < reqs.size(); i++) {
                        long t0 = System.nanoTime();
                        String out = handle(reqs.get(i));
                        long us = (System.nanoTime() - t0) / 1000;
                        sink += out.length();
                        if (i > 0) sb.append(',');
                        sb.append(us);
                    }
                    System.out.println(sb);
                }
                case "SLEEP" -> { Thread.sleep(Long.parseLong(a[1])); System.out.println("OK"); }
                case "QUIT" -> { System.out.println("BYE"); return; }
                default -> System.out.println("ERR " + a[0]);
            }
            System.out.flush();
        }
    }
}
