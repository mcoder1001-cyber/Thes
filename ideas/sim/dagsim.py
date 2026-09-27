#!/usr/bin/env python3
"""dagsim -- discrete-event simulator for snapshot policies on serverless DAG workflows.

Question it answers: once every stage of a workflow HAS a snapshot, what does knowing
the DAG buy you? Single-function snapshot systems (SnapStart, Prebaking, Pronghorn)
restore a stage when its request arrives, so a depth-d workflow that missed
keep-alive pays d restores in series. A DAG-aware orchestrator knows, at the moment
the workflow is invoked, every stage that may run and roughly when -- so it can start
those restores in parallel, ahead of need, speculate cheaply on branches, spend the
leftover slack re-warming, and pick the snapshot variant matching the edge a request
arrives on.

Policies (all share the same arrivals, branch outcomes and jitter draws):
  cold          no keep-alive, no snapshots                      (lower bound on effort)
  keepalive     OpenWhisk-style TTL keep-alive, LRU under memory budget
  snap          keepalive + restore-on-demand from a snapshot    (SnapStart/Pronghorn per function)
  prewarm       keepalive + DAG-aware COLD prewarm ahead of need (Xanadu/ORION style)
  ahead         keepalive + DAG-aware RESTORE ahead of need      (proposed)
  ahead+rw      ahead + re-warm restored sandboxes with synthetic requests during slack
  ahead+rw+ctx  ahead+rw + per-edge (context-keyed) snapshot variants
Any policy can be run with ttl=0 (no keep-alive at all).

Model simplifications (stated, not hidden):
  * warm-up is lumped into a sandbox's first request (total preserved, distribution not);
  * one request per sandbox at a time (OpenWhisk default);
  * the memory budget constrains what is kept idle or started ahead; demand-driven
    starts always proceed (so queueing does not confound latency) and are counted;
  * inter-stage data transfer is a constant per-edge overhead.
"""
import heapq
import math
import random
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

EDGE_MS = 2.0          # orchestrator overhead per DAG edge


# ============================================================ calibration
@dataclass
class Profile:
    """Per-function costs, in ms and MB. Defaults are the thesis's own measurements."""
    name: str
    A: float        # cold: process start + load + framework init
    B: float        # full JIT warm-up after a cold start (lumped into first request)
    C: float        # steady-state execution
    r: float        # snapshot restore wall-clock (CRIU/CRaC)
    RK: float       # residual warm-up after restoring the chosen-depth snapshot (incl. checkpoint loss L)
    m: float        # resident memory while alive
    R_mis: float = None   # residual when the snapshot was primed on the WRONG edge's inputs
    C_cv: float = 0.25
    rho: float = 0.95     # geometric decay of the warm-up curve used for re-warming

    def __post_init__(self):
        if self.R_mis is None:
            self.R_mis = self.RK


# java-spring @1 vCPU: A=2510, B=370 (RESEARCH_PLAN §3, exp3b); 3-stage warm ~35 ms -> C~12;
# exp15 3-stage K=50 total 225 ms -> residual ~63 ms/stage; restore wall-clock 642-9053 ms
# for Spring Boot under quota (MODEL.md scope note) -- 650 is the optimistic end.
JAVA = Profile("java", A=2510, B=370, C=12, r=650, RK=63, m=512)
# CPython: no JIT to capture (B~0-19 ms, exp5); import-heavy init; small restore.
PY = Profile("python", A=400, B=15, C=20, r=60, RK=5, m=256)
# ML-ish stage: long steady execution (gives downstream stages real slack)
PYML = Profile("py-ml", A=1800, B=40, C=300, r=180, RK=20, m=1024)


# ============================================================ DAGs
@dataclass
class Node:
    name: str
    fn: str                         # function id (nodes may share a function: fan-out)
    prof: Profile
    succ: List[str] = field(default_factory=list)                   # AND-successors
    choice: Optional[List[Tuple[float, List[str]]]] = None          # XOR alternatives
    ctx_from: Optional[Dict[str, str]] = None   # pred-name -> context label on this edge


@dataclass
class DAG:
    name: str
    nodes: Dict[str, Node]
    entry: str

    def preds(self):
        p = {n: [] for n in self.nodes}
        for n in self.nodes.values():
            for s in n.succ:
                p[s].append(n.name)
            for _, alt in (n.choice or []):
                for s in alt:
                    p[s].append(n.name)
        return p

    def reach_prob(self, samples=4000):
        """P(node executes), by sampling branch outcomes (general for any XOR/AND mix)."""
        if getattr(self, "_pr", None) is not None:
            return self._pr
        preds, order = self.preds(), self.topo()
        rng = random.Random(12345)
        hits = {n: 0 for n in self.nodes}
        for _ in range(samples):
            live = {self.entry}
            routed = set()          # (pred, succ) edges that carried control this sample
            for n in order:
                if n != self.entry and not any((p, n) in routed for p in preds[n]):
                    continue
                live.add(n)
                node = self.nodes[n]
                for x in node.succ:
                    routed.add((n, x))
                if node.choice:
                    u, acc, chosen = rng.random(), 0.0, node.choice[-1][1]
                    for p, alt in node.choice:
                        acc += p
                        if u < acc:
                            chosen = alt
                            break
                    for x in chosen:
                        routed.add((n, x))
            for n in live:
                hits[n] += 1
        self._pr = {n: hits[n] / samples for n in self.nodes}
        return self._pr

    def topo(self):
        preds = self.preds()
        indeg = {n: len(preds[n]) for n in self.nodes}
        q = [n for n in self.nodes if indeg[n] == 0]
        out = []
        while q:
            n = q.pop()
            out.append(n)
            node = self.nodes[n]
            outs = list(node.succ) + [s for _, alt in (node.choice or []) for s in alt]
            for s in outs:
                indeg[s] -= 1
                if indeg[s] == 0:
                    q.append(s)
        return out


def chain(d, prof=JAVA, tag="chain"):
    nodes = {}
    for i in range(d):
        nodes[f"s{i}"] = Node(f"s{i}", f"{tag}.f{i}", prof, succ=[f"s{i+1}"] if i < d - 1 else [])
    return DAG(f"{tag}{d}", nodes, "s0")


def trip_booking(tag="trip"):
    """SeBS-Flow-style saga: reserve x3, then confirm (0.9) or compensate in reverse (0.1)."""
    J = JAVA
    n = {
        "hotel": Node("hotel", f"{tag}.hotel", J, succ=["flight"]),
        "flight": Node("flight", f"{tag}.flight", J, succ=["car"]),
        "car": Node("car", f"{tag}.car", J, choice=[(0.9, ["confirm"]), (0.1, ["cancel_car"])]),
        "confirm": Node("confirm", f"{tag}.confirm", J, succ=["notify"]),
        "cancel_car": Node("cancel_car", f"{tag}.cancel_car", J, succ=["cancel_flight"]),
        "cancel_flight": Node("cancel_flight", f"{tag}.cancel_flight", J, succ=["cancel_hotel"]),
        "cancel_hotel": Node("cancel_hotel", f"{tag}.cancel_hotel", J, succ=["notify"]),
        "notify": Node("notify", f"{tag}.notify", PY),
    }
    return DAG("trip", n, "hotel")


def fanout(width=4, tag="video"):
    """split -> width x map (same function) -> reduce -> store."""
    n = {"split": Node("split", f"{tag}.split", PY, succ=[f"map{i}" for i in range(width)])}
    for i in range(width):
        n[f"map{i}"] = Node(f"map{i}", f"{tag}.map", JAVA, succ=["reduce"])
    n["reduce"] = Node("reduce", f"{tag}.reduce", JAVA, succ=["store"])
    n["store"] = Node("store", f"{tag}.store", PY)
    return DAG("fanout", n, "split")


def router(tag="router", enrich=None):
    """ingest -> route -> {a (0.6) | b (0.3) | c (0.1)} x2 -> enrich (context = branch) -> respond.

    `enrich` is the stage fed by three different edges: the context-keyed-snapshot case.
    """
    e = enrich or JAVA
    J = JAVA
    n = {
        "ingest": Node("ingest", f"{tag}.ingest", PY, succ=["route"]),
        "route": Node("route", f"{tag}.route", J, choice=[(0.6, ["a1"]), (0.3, ["b1"]), (0.1, ["c1"])]),
        "a1": Node("a1", f"{tag}.a1", J, succ=["a2"]), "a2": Node("a2", f"{tag}.a2", J, succ=["enrich"]),
        "b1": Node("b1", f"{tag}.b1", J, succ=["b2"]), "b2": Node("b2", f"{tag}.b2", J, succ=["enrich"]),
        "c1": Node("c1", f"{tag}.c1", PYML, succ=["c2"]), "c2": Node("c2", f"{tag}.c2", J, succ=["enrich"]),
        "enrich": Node("enrich", f"{tag}.enrich", e, succ=["respond"],
                       ctx_from={"a2": "a", "b2": "b", "c2": "c"}),
        "respond": Node("respond", f"{tag}.respond", PY),
    }
    return DAG("router", n, "ingest")


def ml_pipeline(tag="ml"):
    """preprocess (py) -> infer (long, py-ml) -> post (java) -> index (java) -> notify (py)."""
    n = {
        "pre": Node("pre", f"{tag}.pre", PY, succ=["infer"]),
        "infer": Node("infer", f"{tag}.infer", PYML, succ=["post"]),
        "post": Node("post", f"{tag}.post", JAVA, succ=["index"]),
        "index": Node("index", f"{tag}.index", JAVA, succ=["notify"]),
        "notify": Node("notify", f"{tag}.notify", PY),
    }
    return DAG("ml", n, "pre")


# ============================================================ policy
@dataclass
class Policy:
    name: str
    ttl: float = 600_000.0          # keep-alive, ms
    snap: bool = False              # restore from snapshot instead of cold boot
    ahead: Optional[str] = None     # None | "restore" | "cold"
    theta: float = 0.05             # speculate on a node if P(reach) >= theta
    rewarm: bool = False
    ctx: bool = False               # context-keyed snapshot variants
    margin: float = 0.1             # trigger restore this fraction of r earlier than needed
    gate: bool = False              # plan ahead only if the entry function has no live sandbox
    jit: bool = False               # trigger each restore r_v before its start in the EAGER
                                    # schedule (theory/DAG_SNAPSHOT_THEORY.md, Theorem 2)
    # memory guard (Theorem 8): a demand start that does not fit PREEMPTS ahead-of-time
    # sandboxes not yet claimed by their node (newest first) instead of overflowing the budget;
    # ahead restores may only fill the budget up to (1 - headroom)
    preempt: bool = False
    headroom: float = 0.0
    ahead_evicts: bool = True       # may an ahead restore evict other workflows' idle sandboxes?


POLICIES = {
    "cold": Policy("cold", ttl=0.0),
    "keepalive": Policy("keepalive"),
    "snap": Policy("snap", snap=True),
    "prewarm": Policy("prewarm", ahead="cold", theta=0.5),
    "ahead": Policy("ahead", snap=True, ahead="restore"),
    "ahead+rw": Policy("ahead+rw", snap=True, ahead="restore", rewarm=True),
    "ahead+rw+ctx": Policy("ahead+rw+ctx", snap=True, ahead="restore", rewarm=True, ctx=True),
    # restore ahead only when the workflow is cold (its entry function has no live sandbox):
    # avoids restoring for stages whose warm sandbox is merely busy under load
    "ahead+rw/gated": Policy("ahead+rw/gated", snap=True, ahead="restore", rewarm=True, gate=True),
    # the policy the theory recommends: gated, just-in-time triggers (Theorem 2), with a
    # safety margin of 0.3 r against restore-time jitter (Theorem 3 gives the exact quantile)
    "ahead+rw/gated/jit": Policy("ahead+rw/gated/jit", snap=True, ahead="restore", rewarm=True,
                                 gate=True, jit=True, margin=0.3),
    # the same with the memory guard (Theorem 8(c)): demand starts preempt unclaimed look-ahead
    # sandboxes. In a burst this removes look-ahead's overflow; on a trace below its working set,
    # look-ahead's evictions of idle sandboxes still add some (e7b; see ahead_evicts)
    "ahead+rw/gated/jit/guard": Policy("ahead+rw/gated/jit/guard", snap=True, ahead="restore", rewarm=True,
                                       gate=True, jit=True, margin=0.3, preempt=True),
}


def ttl0(p: Policy) -> Policy:
    q = Policy(**{**p.__dict__})
    q.name, q.ttl = p.name + "@ttl0", 0.0
    return q


# ============================================================ sandboxes
BOOT, RESTORE, IDLE, BUSY = "boot", "restore", "idle", "busy"


@dataclass
class Sandbox:
    sid: int
    fn: str
    prof: Profile
    state: str
    ready_at: float
    origin: str                 # "cold" | "snap"
    served: int = 0
    last_used: float = 0.0
    reserved: Optional[Tuple[int, str]] = None  # (invocation id, node name)
    ctxs: frozenset = frozenset()               # contexts this sandbox is warm for
    variant: Optional[str] = None               # snapshot variant it was restored from
    ahead: bool = False
    claimed: bool = False                        # taken by a started node (not just reserved)
    waiting: list = field(default_factory=list)  # requests queued on a not-yet-ready sandbox
    ver: int = 0


def rewarm_residual(R, C, slack, rho):
    """Residual warm-up after running synthetic requests back-to-back for `slack` ms.

    Warm-up curve e(i) = R(1-rho) rho^i; each synthetic request costs C + e(i) and is
    only started if it finishes before the real input is due.
    """
    if slack <= 0 or R <= 0:
        return R, 0.0
    used, left, i = 0.0, R, 0
    while True:
        e = R * (1 - rho) * rho ** i
        if used + C + e > slack or e < 1e-3:
            return left, used
        used += C + e
        left -= e
        i += 1


# ============================================================ simulator
class Sim:
    def __init__(self, policy: Policy, mem_budget_mb: float = 64_000, restore_beta: float = 0.0,
                 seed: int = 0, jitter: bool = True):
        self.p = policy
        self.M = mem_budget_mb
        self.beta = restore_beta
        self.seed = seed
        self.jitter = jitter
        self.ev = []
        self.seq = 0
        self.now = 0.0
        self.sb: Dict[str, List[Sandbox]] = {}
        self.nsid = 0
        self.mem = 0.0
        self.mem_last = 0.0
        self.memtime = 0.0          # MB*ms, all sandboxes
        self.idle_memtime = 0.0     # MB*ms, idle (kept warm or restored-ahead, waiting)
        self.idle_mem = 0.0
        self.restoring = 0
        self.stats = dict(cold_boots=0, restores=0, ahead_started=0, ahead_unused=0,
                          warm_hits=0, overflow=0, rewarm_ms=0.0, ctx_miss=0, evictions=0,
                          preempted=0)
        self.peak_mem = 0.0
        self.over_memtime = 0.0     # MB*ms spent above the budget (demand overflow)
        self.inv = {}
        self.ninv = 0
        self.wcount = {}
        self.results = []

    # ---------------------------------------------------------------- plumbing
    def push(self, t, kind, *args):
        self.seq += 1
        heapq.heappush(self.ev, (t, self.seq, kind, args))

    def _acct(self):
        dt = self.now - self.mem_last
        if dt > 0:
            self.memtime += self.mem * dt
            self.idle_memtime += self.idle_mem * dt
            self.over_memtime += max(0.0, self.mem - self.M) * dt
        self.mem_last = self.now

    def _set_state(self, s: Sandbox, state):
        self._acct()
        if s.state == IDLE:
            self.idle_mem -= s.prof.m
        if state == IDLE:
            self.idle_mem += s.prof.m
        s.state = state
        s.ver += 1

    def _new(self, fn, prof, origin, dur, ahead=False, variant=None, demand=True):
        need = prof.m
        limit = self.M if demand else self.M * (1.0 - self.p.headroom)
        if self.mem + need > limit and (demand or self.p.ahead_evicts):
            self._evict(self.mem + need - limit)
        if self.mem + need > limit and demand and self.p.preempt:
            self._preempt(self.mem + need - limit)
        if self.mem + need > limit:
            if not demand:
                return None
            self.stats["overflow"] += 1
        self._acct()
        self.nsid += 1
        s = Sandbox(self.nsid, fn, prof, RESTORE if origin == "snap" else BOOT,
                    self.now + dur, origin, ahead=ahead, variant=variant)
        self.mem += need
        self.peak_mem = max(self.peak_mem, self.mem)
        self.sb.setdefault(fn, []).append(s)
        if origin == "snap":
            self.stats["restores"] += 1
            self.restoring += 1
        else:
            self.stats["cold_boots"] += 1
        if ahead:
            self.stats["ahead_started"] += 1
        self.push(s.ready_at, "ready", s, s.ver)
        return s

    def _kill(self, s: Sandbox):
        self._set_state(s, "dead")
        self._acct()
        self.mem -= s.prof.m
        self.sb[s.fn].remove(s)

    def _evict(self, amount):
        idle = [s for lst in self.sb.values() for s in lst if s.state == IDLE and s.reserved is None]
        idle.sort(key=lambda s: s.last_used)
        freed = 0.0
        for s in idle:
            if freed >= amount:
                break
            freed += s.prof.m
            self._kill(s)
            self.stats["evictions"] += 1

    def _preempt(self, amount):
        """Free memory for a demand start by killing ahead-of-time sandboxes that no node has
        claimed yet, newest first; their nodes fall back to a demand start when their input
        arrives (Theorem 8(c): this is what keeps capped look-ahead from deadlocking)."""
        cand = [s for lst in self.sb.values() for s in lst
                if s.ahead and s.reserved is not None and not s.claimed and not s.waiting
                and s.state in (IDLE, RESTORE, BOOT)]
        cand.sort(key=lambda s: -s.sid)
        freed = 0.0
        for s in cand:
            if freed >= amount:
                break
            if s.state == RESTORE:
                self.restoring -= 1
            freed += s.prof.m
            self._kill(s)
            self.stats["preempted"] += 1

    def _restore_time(self, prof, rng):
        r = prof.r * rng.lognormvariate(0, 0.15)
        return r * (1 + self.beta * self.restoring)

    # ---------------------------------------------------------------- workflow
    def invoke(self, t, dag: DAG, wid):
        self.push(t, "arrive", dag, wid)

    def _arrive(self, dag: DAG, wid):
        self.ninv += 1
        iid = self.ninv
        k = self.wcount.get(wid, 0)
        self.wcount[wid] = k + 1
        # zlib.crc32, not hash(): str hashing is salted per process (PYTHONHASHSEED)
        rng = random.Random(zlib.crc32(repr((self.seed, wid, k)).encode()))
        # pre-draw every random quantity so all policies see identical outcomes
        j = 1.0 if self.jitter else 0.0
        draws = {n: dict(c=rng.lognormvariate(0, j * dag.nodes[n].prof.C_cv),
                         a=rng.lognormvariate(0, j * 0.1), r=rng.lognormvariate(0, j * 0.15),
                         u=rng.random()) for n in dag.nodes}
        st = dict(dag=dag, wid=wid, t0=self.now, done=set(), skipped=set(), started=set(),
                  draws=draws, ctx={}, preds=dag.preds(), fin={})
        self.inv[iid] = st
        if self.p.ahead and not (self.p.gate and self.sb.get(dag.nodes[dag.entry].fn)):
            self._plan_ahead(iid)
        self._start_node(iid, dag.entry)

    def _plan_ahead(self, iid):
        """At workflow arrival: for every downstream node, schedule a restore (or cold
        prewarm) so that it is ready when the node's input is expected."""
        st = self.inv[iid]
        dag, draws = st["dag"], st["draws"]
        pr = dag.reach_prob()
        preds = st["preds"]
        need = {}           # fn -> count of sandboxes this invocation will need
        est_start, est_fin = {}, {}
        for n in dag.topo():
            node = dag.nodes[n]
            ps = preds[n]
            est_start[n] = 0.0 if not ps else max(est_fin[p] for p in ps) + EDGE_MS
            if self.p.jit and n != dag.entry and self.p.ahead == "restore":
                # eager-schedule start S*_v = max(input time, own restore completion)
                est_start[n] = max(est_start[n], node.prof.r)
            if n == dag.entry:
                dur = node.prof.C + (0 if self._idle_count(node.fn) else
                                     (node.prof.r + node.prof.RK if self.p.ahead == "restore"
                                      else node.prof.A + node.prof.B))
            else:
                dur = node.prof.C + (node.prof.RK if self.p.ahead == "restore" else node.prof.B)
            est_fin[n] = est_start[n] + dur
        for n in dag.topo():
            if n == dag.entry or pr[n] < self.p.theta:
                continue
            node = dag.nodes[n]
            variants = [None]
            if self.p.ctx and node.ctx_from:
                # one variant per incoming edge worth speculating on
                variants = sorted({c for p, c in node.ctx_from.items() if pr[p] >= self.p.theta})
            for var in variants:
                k = need.get((node.fn, var), 0)
                need[(node.fn, var)] = k + 1
                lead = node.prof.r if self.p.ahead == "restore" else node.prof.A
                t = max(0.0, est_start[n] - lead * (1 + self.p.margin))
                self.push(self.now + t, "ahead", iid, n, var, k)

    def _fits(self, s, var):
        """Can idle sandbox s serve context var without a mis-primed first request?"""
        if var is None or not self.p.ctx:
            return True
        return var in s.ctxs if s.served else s.variant == var

    def _idle_count(self, fn):
        return sum(1 for s in self.sb.get(fn, []) if s.state == IDLE and s.reserved is None)

    def _ahead(self, iid, n, var, k):
        st = self.inv.get(iid)
        if st is None or n in st["started"] or n in st["skipped"]:
            return
        node = st["dag"].nodes[n]
        # already have enough reserved / idle warm sandboxes for this node?
        mine = [s for s in self.sb.get(node.fn, []) if s.reserved and s.reserved[0] == iid
                and (var is None or s.variant == var)]
        if len(mine) > k:
            return
        free = [s for s in self.sb.get(node.fn, [])
                if s.state == IDLE and s.reserved is None and self._fits(s, var)]
        if free:
            free[0].reserved = (iid, n)
            return
        d = st["draws"][n]
        if self.p.ahead == "restore":
            dur = self._restore_time(node.prof, _Fixed(d["r"]))
            s = self._new(node.fn, node.prof, "snap", dur, ahead=True, variant=var, demand=False)
        else:
            s = self._new(node.fn, node.prof, "cold", node.prof.A * d["a"], ahead=True, demand=False)
        if s is not None:
            s.reserved = (iid, n)

    def _start_node(self, iid, n):
        st = self.inv[iid]
        st["started"].add(n)
        node = st["dag"].nodes[n]
        d = st["draws"][n]
        ctx = st["ctx"].get(n)
        lst = self.sb.get(node.fn, [])
        # 1) a sandbox reserved ahead for this invocation and not yet claimed by a sibling
        #    node (fan-out siblings share a function; an earlier rule keyed on node names
        #    let one sibling take another's reservation and left the last ones without --
        #    caught by the fan-out closed-form control in run_sim.py e0)
        cand = [s for s in lst if s.reserved and s.reserved[0] == iid and not s.claimed
                and s.state in (IDLE, RESTORE, BOOT)]
        if ctx is not None and self.p.ctx:
            cand.sort(key=lambda s: (s.variant != ctx, s.ready_at))
        else:
            cand.sort(key=lambda s: s.ready_at)
        s = cand[0] if cand else None
        # 2) an idle warm sandbox
        if s is None:
            idle = [x for x in lst if x.state == IDLE and x.reserved is None]
            if idle:
                idle.sort(key=lambda x: -x.last_used)
                s = idle[0]
        # 3) demand start
        if s is None:
            if self.p.snap:
                s = self._new(node.fn, node.prof, "snap", self._restore_time(node.prof, _Fixed(d["r"])),
                              variant=ctx if self.p.ctx else None)
            else:
                s = self._new(node.fn, node.prof, "cold", node.prof.A * d["a"])
        s.reserved = (iid, n)
        s.claimed = True
        req = (iid, n, self.now)
        if s.state == IDLE:
            self._serve(s, req)
        else:
            s.waiting.append(req)

    def _serve(self, s: Sandbox, req):
        iid, n, t_req = req
        st = self.inv[iid]
        node = st["dag"].nodes[n]
        d = st["draws"][n]
        prof = node.prof
        ctx = st["ctx"].get(n)
        dur = prof.C * d["c"]
        if s.served == 0:
            if s.origin == "cold":
                dur += prof.B
            else:
                R = prof.RK
                if ctx is not None and node.ctx_from:
                    primed = s.variant if self.p.ctx else self._dominant_ctx(node)
                    if primed != ctx:
                        R = prof.R_mis
                        self.stats["ctx_miss"] += 1
                if self.p.rewarm and s.ahead:
                    slack = self.now - s.ready_at
                    R, used = rewarm_residual(R, prof.C, slack, prof.rho)
                    self.stats["rewarm_ms"] += used
                dur += R
        elif ctx is not None and node.ctx_from and ctx not in s.ctxs and s.ctxs:
            # warm sandbox meeting a new edge for the first time
            dur += prof.R_mis - prof.RK if prof.R_mis > prof.RK else 0.0
        if s.served > 0:
            self.stats["warm_hits"] += 1
        self._set_state(s, BUSY)
        s.served += 1
        if ctx is not None:
            s.ctxs = s.ctxs | {ctx}
        self.push(self.now + dur, "finish", s, req)

    @staticmethod
    def _dominant_ctx(node):
        return next(iter(node.ctx_from.values()))

    def _finish(self, s: Sandbox, req):
        iid, n, _ = req
        st = self.inv[iid]
        dag = st["dag"]
        st["done"].add(n)
        st["fin"][n] = self.now
        self._release(s)
        node = dag.nodes[n]
        nxt = list(node.succ)
        if node.choice:
            u = st["draws"][n]["u"]
            acc = 0.0
            chosen = node.choice[-1][1]
            for p, alt in node.choice:
                acc += p
                if u < acc:
                    chosen = alt
                    break
            nxt += chosen
            for _, alt in node.choice:
                if alt is not chosen:
                    for x in alt:
                        self._skip(iid, x)
        for x in nxt:
            if dag.nodes[x].ctx_from and n in dag.nodes[x].ctx_from:
                st["ctx"][x] = dag.nodes[x].ctx_from[n]
            self._maybe_start(iid, x)
        self._maybe_complete(iid)

    def _skip(self, iid, n):
        st = self.inv[iid]
        if n in st["skipped"] or n in st["done"] or n in st["started"]:
            return
        preds = st["preds"][n]
        if not all(p in st["skipped"] for p in preds) and len(preds) > 1:
            # a join with a live predecessor is not skipped
            live = [p for p in preds if p not in st["skipped"]]
            if live:
                return
        st["skipped"].add(n)
        node = st["dag"].nodes[n]
        for x in list(node.succ) + [y for _, alt in (node.choice or []) for y in alt]:
            self._skip(iid, x)
            if x not in st["skipped"]:
                self._maybe_start(iid, x)

    def _maybe_start(self, iid, n):
        st = self.inv[iid]
        if n in st["started"] or n in st["skipped"]:
            return
        preds = st["preds"][n]
        if all(p in st["done"] or p in st["skipped"] for p in preds) and any(p in st["done"] for p in preds):
            self.push(self.now + EDGE_MS, "start", iid, n)

    def _maybe_complete(self, iid):
        st = self.inv[iid]
        dag = st["dag"]
        if all(n in st["done"] or n in st["skipped"] for n in dag.nodes):
            lat = self.now - st["t0"]
            self.results.append((st["wid"], dag.name, st["t0"], lat))
            # release reservations this invocation never used (speculation that missed)
            for lst in self.sb.values():
                for s in list(lst):
                    if s.reserved and s.reserved[0] == iid:
                        self.stats["ahead_unused"] += 1
                        s.reserved = None
                        s.ahead = False
                        if s.state == IDLE:
                            self._to_idle_or_die(s)
            del self.inv[iid]

    def _release(self, s: Sandbox):
        s.reserved = None
        s.claimed = False
        s.last_used = self.now
        if s.waiting:
            self._set_state(s, IDLE)
            req = s.waiting.pop(0)
            s.reserved = (req[0], req[1])
            s.claimed = True
            self._serve(s, req)
            return
        self._set_state(s, IDLE)
        self._to_idle_or_die(s)

    def _to_idle_or_die(self, s: Sandbox):
        if s.reserved is not None:
            return
        if self.p.ttl <= 0:
            self._kill(s)
        else:
            self.push(self.now + self.p.ttl, "expire", s, s.ver)

    def _ready(self, s: Sandbox, ver):
        if s.ver != ver or s.state not in (BOOT, RESTORE):
            return
        if s.state == RESTORE:
            self.restoring -= 1
        s.ready_at = self.now
        self._set_state(s, IDLE)
        if s.waiting:
            req = s.waiting.pop(0)
            self._serve(s, req)
        elif s.reserved is None:
            self._to_idle_or_die(s)

    def _expire(self, s: Sandbox, ver):
        if s.ver == ver and s.state == IDLE and s.reserved is None:
            self._kill(s)

    # ---------------------------------------------------------------- run
    def run(self, until=math.inf):
        while self.ev:
            t, _, kind, args = heapq.heappop(self.ev)
            if t > until:
                break
            self.now = t
            if kind == "arrive":
                self._arrive(*args)
            elif kind == "start":
                self._start_node(*args)
            elif kind == "finish":
                self._finish(*args)
            elif kind == "ready":
                self._ready(*args)
            elif kind == "expire":
                self._expire(*args)
            elif kind == "ahead":
                self._ahead(*args)
        self._acct()
        return self


class _Fixed:
    """Replays a pre-drawn lognormal factor so restore jitter is identical across policies."""
    def __init__(self, f):
        self.f = f

    def lognormvariate(self, *_):
        return self.f


def pct(xs, q):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
