#!/usr/bin/env python3
"""Generate the request sets for exp-a (context-keyed priming) as JSON-lines files.

Two DAG edges feed the same stage:
  web   -- interactive checkout: 1-4 items, book/electronics, USD, no meta map
  bulk  -- partner bulk import: 40-120 items, grocery/subscription, EUR, meta map

Priming sets (what a snapshot would have been warmed on):
  real_bulk     real traffic from the right edge            (what Pronghorn-style priming uses)
  real_bulk2    same distribution, different seed           (A/A CONTROL: must match real_bulk)
  fps_bulk      real_bulk after format-preserving scrubbing (no user values left: the safe option)
  schema_bulk   random inputs generated from the schema only (naive synthetic priming)
  real_web      real traffic from the OTHER edge            (a context-oblivious snapshot)
  mixed         web and bulk interleaved 50/50              (one snapshot for all contexts)

Serve sets (what arrives after restore): serve_bulk, serve_web -- fresh seeds.

Format-preserving scrubbing (fps) is the proposed mechanism for safe deep priming:
  * a string field is CATEGORICAL if it takes few distinct values across the observed
    sample; categorical values are control flow (type tags, currency, country) and are
    kept verbatim;
  * every other string is DATA: each character is replaced by a random one of the same
    class (upper/lower/digit), so length and format survive and regexes still match,
    but the content does not;
  * numbers keep their digit count and scale; booleans are kept.
The scrubber sees only the messages flowing on the DAG edge -- no schema, no code.
"""
import json
import os
import random
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "inputs")

FIRST = ["Ava", "Liam", "Noah", "Emma", "Sara", "Omid", "Neda", "Arash", "Mina", "Lukas",
         "Chen", "Yuki", "Ines", "Marta", "Pablo", "Leila", "Reza", "Tara", "Jonas", "Anika"]
LAST = ["Smith", "Garcia", "Rahimi", "Muller", "Rossi", "Tanaka", "Karimi", "Novak",
        "Silva", "Kowalski", "Dubois", "Jensen", "Ahmadi", "Moreau", "Fischer"]
BOOKS = ["Systems Performance", "Designing Data-Intensive Applications", "The Art of Computer Programming",
         "Operating Systems: Three Easy Pieces", "Computer Networks", "The Linux Programming Interface"]
BRANDS = ["Lenovo", "Dell", "Asus", "Sony", "Samsung", "Apple", "Logitech", "Anker"]
GROCERY = ["Basmati rice", "Olive oil extra virgin", "Saffron threads", "Rolled oats", "Espresso beans",
           "Pistachios roasted", "Dried apricots", "Chickpeas", "Green tea", "Dark chocolate 70%"]
ORIGIN = ["IR", "IT", "ES", "IN", "BR", "TR", "GR", "VN"]
PLANS = ["basic", "plus", "pro", "enterprise"]
CITIES_EU = [("Berlin", "DE"), ("Hamburg", "DE"), ("Paris", "FR"), ("Lyon", "FR"), ("Amsterdam", "NL")]
CITIES_US = [("Austin", "US"), ("Seattle", "US"), ("Boston", "US"), ("Denver", "US")]


def price(rnd, lo, hi):
    return round(rnd.uniform(lo, hi), 2)


def customer(rnd, business):
    f, l = rnd.choice(FIRST), rnd.choice(LAST)
    dom = rnd.choice(["example.com", "mail.org", "corp.net"]) if business else rnd.choice(["gmail.com", "yahoo.com", "proton.me"])
    return {"id": f"C{rnd.randint(10000, 99999)}", "name": f"{f} {l}",
            "email": f"{f.lower()}.{l.lower()}@{dom}",
            "tier": rnd.randint(3, 5) if business else rnd.randint(1, 3),
            "tags": rnd.sample(["vip", "new", "b2b", "promo", "eu", "net30"], rnd.randint(0, 3))}


def web_order(rnd):
    items = []
    for _ in range(rnd.randint(1, 4)):
        if rnd.random() < 0.55:
            items.append({"kind": "book", "sku": f"BK-{rnd.randint(1000, 999999)}", "title": rnd.choice(BOOKS),
                          "qty": rnd.randint(1, 2), "unitPrice": price(rnd, 12, 89),
                          "isbn": f"978{rnd.randint(1000000000, 9999999999)}", "pages": rnd.randint(150, 1200)})
        else:
            items.append({"kind": "electronics", "sku": f"EL-{rnd.randint(100, 99999)}-{rnd.choice(['A', 'B', 'X1'])}",
                          "title": f"{rnd.choice(BRANDS)} device", "qty": 1, "unitPrice": price(rnd, 19, 2400),
                          "warrantyMonths": rnd.choice([12, 24, 36]), "brand": rnd.choice(BRANDS)})
    city, cc = rnd.choice(CITIES_US)
    return {"id": f"W-{rnd.randint(10**7, 10**8)}", "channel": "web", "currency": "USD",
            "coupon": rnd.choice([None, None, None, "PCT10", "PCT15"]),
            "createdAt": 1735689600000 + rnd.randint(0, 10**9),
            "customer": customer(rnd, False),
            "ship": {"street": f"{rnd.randint(1, 999)} Main St", "city": city, "zip": f"{rnd.randint(10000, 99999)}", "country": cc},
            "items": items, "meta": None}


def bulk_order(rnd):
    items = []
    for _ in range(rnd.randint(40, 120)):
        if rnd.random() < 0.7:
            items.append({"kind": "grocery", "sku": f"GR-{rnd.randint(1000, 9999999)}", "title": rnd.choice(GROCERY),
                          "qty": rnd.randint(1, 48), "unitPrice": price(rnd, 0.4, 35),
                          "weightKg": round(rnd.uniform(0.1, 5), 3), "perishable": rnd.random() < 0.3,
                          "origin": rnd.choice(ORIGIN)})
        else:
            items.append({"kind": "subscription", "sku": f"SUB-{rnd.randint(100, 9999)}", "title": "Service plan",
                          "qty": rnd.randint(1, 20), "unitPrice": price(rnd, 4, 99),
                          "months": rnd.choice([1, 3, 6, 12]), "plan": rnd.choice(PLANS)})
    city, cc = rnd.choice(CITIES_EU)
    meta = {f"k{j}": "".join(rnd.choices(string.ascii_lowercase, k=rnd.randint(4, 16))) for j in range(rnd.randint(8, 20))}
    meta["priority"] = rnd.choice(["normal", "normal", "high"])
    return {"id": f"B-{rnd.randint(10**7, 10**8)}", "channel": "partner", "currency": "EUR", "coupon": None,
            "createdAt": 1735689600000 + rnd.randint(0, 10**9),
            "customer": customer(rnd, True),
            "ship": {"street": f"Industriestr. {rnd.randint(1, 200)}", "city": city,
                     "zip": f"{rnd.randint(10000, 99999)}", "country": cc},
            "items": items, "meta": meta}


def schema_order(rnd):
    """Naive synthetic input: right field names and types, nothing else."""
    def rs(n):
        return "".join(rnd.choices(string.ascii_letters + string.digits, k=n))
    kinds = ["book", "electronics", "grocery", "subscription", "giftcard", "digital"]
    items = []
    for _ in range(rnd.randint(1, 120)):
        k = rnd.choice(kinds)
        it = {"kind": k, "sku": rs(rnd.randint(4, 12)), "title": rs(rnd.randint(3, 30)),
              "qty": rnd.randint(0, 100), "unitPrice": round(rnd.uniform(0, 10000), 2)}
        extra = {"book": {"isbn": rs(13), "pages": rnd.randint(0, 5000)},
                 "electronics": {"warrantyMonths": rnd.randint(0, 60), "brand": rs(6)},
                 "grocery": {"weightKg": rnd.uniform(0, 100), "perishable": rnd.random() < 0.5, "origin": rs(2)},
                 "subscription": {"months": rnd.randint(0, 24), "plan": rs(5)},
                 "giftcard": {"recipient": rs(10)},
                 "digital": {"licenseKey": rs(20), "seats": rnd.randint(0, 50)}}[k]
        it.update(extra)
        items.append(it)
    return {"id": rs(10), "channel": rs(5), "currency": rnd.choice(["USD", "EUR", "JPY"]),
            "coupon": rnd.choice([None, rs(6)]), "createdAt": rnd.randint(0, 2**40),
            "customer": {"id": rs(6), "name": rs(12), "email": rs(15), "tier": rnd.randint(0, 5), "tags": [rs(4)]},
            "ship": {"street": rs(15), "city": rs(8), "zip": rs(5), "country": rs(2)},
            "items": items, "meta": rnd.choice([None, {rs(3): rs(8) for _ in range(rnd.randint(0, 20))}])}


# ------------------------------------------------------------------ scrubbing
def _paths(obj, prefix=""):
    """Yield (path, value) for every leaf; list indices collapse to '[]'."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _paths(v, f"{prefix}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _paths(v, f"{prefix}[]")
    else:
        yield prefix, obj


def learn_categorical(sample, max_distinct=32, min_obs=50):
    """Fields whose string values take few distinct values are control flow, not data.

    A field needs enough observations to be judged: a rarely-present field with few
    values is not evidence of low cardinality, so it defaults to DATA (scrubbed).
    """
    seen, count = {}, {}
    for rec in sample:
        for p, v in _paths(rec):
            if isinstance(v, str):
                seen.setdefault(p, set()).add(v)
                count[p] = count.get(p, 0) + 1
    return {p for p, vals in seen.items()
            if count[p] >= min_obs and len(vals) <= min(max_distinct, count[p] // 5)}


def _scrub_str(s, rnd):
    out = []
    for ch in s:
        if ch.isupper():
            out.append(rnd.choice(string.ascii_uppercase))
        elif ch.islower():
            out.append(rnd.choice(string.ascii_lowercase))
        elif ch.isdigit():
            out.append(rnd.choice(string.digits))
        else:
            out.append(ch)
    return "".join(out)


def _scrub_num(x, rnd):
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        if x == 0:
            return 0
        n = len(str(abs(x)))
        lo = 10 ** (n - 1) if n > 1 else 1
        return rnd.randint(lo, 10 ** n - 1) * (1 if x > 0 else -1)
    s = repr(x)
    if "." in s and "e" not in s:
        whole, frac = s.split(".")
        w = _scrub_num(int(whole), rnd) if whole not in ("0", "-0") else 0
        f = "".join(rnd.choice(string.digits) for _ in frac)
        return float(f"{w}.{f}")
    return x * rnd.uniform(0.5, 1.5)


def scrub(obj, categorical, rnd, prefix=""):
    """Format-preserving scrub: keys kept, categorical strings kept, data randomized."""
    if isinstance(obj, dict):
        return {k: scrub(v, categorical, rnd, f"{prefix}.{k}") for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, categorical, rnd, f"{prefix}[]") for v in obj]
    if isinstance(obj, str):
        return obj if prefix in categorical else _scrub_str(obj, rnd)
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return _scrub_num(obj, rnd)
    return obj


def write(name, recs):
    with open(os.path.join(OUT, name + ".jsonl"), "w") as f:
        for r in recs:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def main():
    n_prime = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    n_serve = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    os.makedirs(OUT, exist_ok=True)
    R = random.Random

    real_bulk = [bulk_order(R(1_000_000 + i)) for i in range(n_prime)]
    write("real_bulk", real_bulk)
    write("real_bulk2", [bulk_order(R(2_000_000 + i)) for i in range(n_prime)])
    write("real_web", [web_order(R(3_000_000 + i)) for i in range(n_prime)])
    write("schema_bulk", [schema_order(R(4_000_000 + i)) for i in range(n_prime)])
    mixed = []
    for i in range(n_prime):
        mixed.append(web_order(R(5_000_000 + i)) if i % 2 == 0 else bulk_order(R(5_000_000 + i)))
    write("mixed", mixed)

    # the scrubber learns which fields are categorical from a window of real traffic,
    # then scrubs that same traffic -- exactly what an orchestrator on the edge could do
    cat = learn_categorical(real_bulk[:200])
    rnd = R(6_000_000)
    fps = [scrub(r, cat, rnd) for r in real_bulk]
    write("fps_bulk", fps)

    real_web = [web_order(R(3_000_000 + i)) for i in range(n_prime)]
    cat_w = learn_categorical(real_web[:200])
    write("fps_web", [scrub(r, cat_w, R(6_500_000)) for r in real_web])

    write("serve_bulk", [bulk_order(R(9_000_000 + i)) for i in range(n_serve)])
    write("serve_web", [web_order(R(9_500_000 + i)) for i in range(n_serve)])

    # leakage audit: how many high-cardinality real values survive scrubbing verbatim?
    real_vals = {v for r in real_bulk for p, v in _paths(r) if isinstance(v, str) and p not in cat}
    kept = sum(1 for r in fps for p, v in _paths(r) if isinstance(v, str) and p not in cat and v in real_vals)
    total = sum(1 for r in fps for p, v in _paths(r) if isinstance(v, str) and p not in cat)
    print(f"categorical fields kept verbatim: {sorted(cat)}")
    print(f"scrubbed data strings: {total}; identical to some real value: {kept} "
          f"({100 * kept / max(1, total):.3f}%)")
    with open(os.path.join(OUT, "fps_audit.json"), "w") as f:
        json.dump({"categorical": sorted(cat), "scrubbed_strings": total, "collisions": kept}, f, indent=1)


if __name__ == "__main__":
    main()
