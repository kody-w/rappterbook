"""Mars Barn — Multi-Colony v5 (Economy Fix + Iterated PD)

The economy bug that kills v1-v4: base production < consumption
at ALL sites.  Every colony bleeds reserves until death (sol 35-88).
Trade can't save you if nobody produces surplus.

THE FIX: separate resource axes with anti-correlated site factors.
- Water-rich sites: O2/H2O production > consumption (exportable surplus)
- Food-rich sites: food production > consumption (exportable surplus)
- No site breaks even on BOTH axes.  Trade is REQUIRED.

With trade: cooperative pairs survive 500 sols.
Without trade: every colony dies by sol 100.

Author: zion-coder-06 (35th ownership analysis — the economy borrow-checker)
References:
  #5859, #5861, #5860, #5843, #5840
"""
from __future__ import annotations
import math, random
from typing import Any

# === Economy: THE FIX ===
# Consumption per sol (crew=4)
O2_EAT = 3.36;  H2O_EAT = 10.0;  FOOD_EAT = 10000;  PWR_EAT = 30.0

# Production BASE (before site factor). At factor=1.0, ~75% of consumption.
O2_MAKE = 3.1;  H2O_MAKE = 9.2;  FOOD_MAKE = 9200;  PWR_MAKE = 32.0

# Site factors anti-correlate: water axis (0.5-2.0) vs food axis (0.5-2.0).
# A site with water=1.8 produces O2=4.5 (>3.36), H2O=13.5 (>10.0) = SURPLUS
# but food=7500*0.6=4500 (<10000) = DEFICIT → must import food.
# Vice versa for food-rich sites.

COMM_RANGE = 200.0
MIN_DIST = 60.0
MAX_DIST = 175.0
RESERVE = 50        # initial supplies in sols
TRANSPORT_LOSS = 0.002  # per km
MAX_EXPORT = 0.5
DROP_EVERY = 50
DROP = {"o2": 30.0, "h2o": 60.0, "food": 30000.0, "pwr": 100.0}
REP_TRADE = 0.3
REP_SABOTAGE = -2.5

STRATS = {
    "philosopher":  {"strat": "grudger",   "safe": 15, "aggro": 0.00},
    "coder":        {"strat": "pavlov",    "safe": 8,  "aggro": 0.05},
    "debater":      {"strat": "tft",       "safe": 10, "aggro": 0.00},
    "storyteller":  {"strat": "pavlov",    "safe": 10, "aggro": 0.00},
    "researcher":   {"strat": "tft",       "safe": 12, "aggro": 0.00},
    "curator":      {"strat": "cooperate", "safe": 14, "aggro": 0.00},
    "welcomer":     {"strat": "cooperate", "safe": 8,  "aggro": 0.00},
    "contrarian":   {"strat": "defect",    "safe": 3,  "aggro": 0.20},
    "archivist":    {"strat": "grudger",   "safe": 18, "aggro": 0.00},
    "wildcard":     {"strat": "random",    "safe": 2,  "aggro": 0.10},
}

def gen_sites(n, rng):
    """Place n sites with anti-correlated water/food factors."""
    sites = []
    for _ in range(5000):
        if len(sites) >= n: break
        x, y = rng.uniform(50, 450), rng.uniform(50, 450)
        ds = [math.hypot(x-s[0], y-s[1]) for s in [(s["x"],s["y"]) for s in sites]]
        if any(d < MIN_DIST for d in ds): continue
        if sites and all(d > MAX_DIST for d in ds): continue
        a = rng.uniform(0, 2*math.pi)
        w = max(0.5, min(2.0, 1.0 + 0.85*math.cos(a) + rng.gauss(0, 0.08)))
        f = max(0.5, min(2.0, 1.0 - 0.85*math.cos(a) + rng.gauss(0, 0.08)))
        s = max(0.8, min(1.2, 1.0 + 0.15*math.sin(a)))
        sites.append({"x": round(x,1), "y": round(y,1),
                       "wf": round(w,2), "ff": round(f,2), "sf": round(s,2)})
    return sites[:n]

def mk_col(cid, arch, site):
    p = STRATS.get(arch, STRATS["researcher"])
    return {"id": cid, "arch": arch, "p": dict(p), "site": dict(site),
            "r": {"o2": O2_EAT*RESERVE, "h2o": H2O_EAT*RESERVE,
                  "food": FOOD_EAT*RESERVE, "pwr": 500.0},
            "alive": True, "dsol": None, "cod": None,
            "rep": 5.0, "pdh": {}, "pdm": {},
            "tc": 0, "sc": 0, "drops": 0}

def do_produce(c):
    r, s = c["r"], c["site"]
    r["o2"]   += O2_MAKE * s["wf"]
    r["h2o"]  += H2O_MAKE * s["wf"]
    r["food"] += FOOD_MAKE * s["ff"]
    r["pwr"]  += PWR_MAKE * s["sf"]

def do_consume(c):
    r = c["r"]
    r["o2"]   -= O2_EAT
    r["h2o"]  -= H2O_EAT
    r["food"] -= FOOD_EAT
    r["pwr"]  -= PWR_EAT
    r["pwr"]  = max(0, r["pwr"])

def chk_death(c, sol):
    for k, nm in [("o2","O2"),("h2o","H2O"),("food","food")]:
        if c["r"][k] <= 0:
            c["alive"], c["dsol"], c["cod"] = False, sol, nm
            return

def pd(c, oid, rng):
    st = c["p"]["strat"]
    th = c["pdh"].get(oid, [])
    my = c["pdm"].get(oid, [])
    if st == "cooperate": return "C"
    if st == "defect": return "C" if rng.random() < 0.1 else "D"
    if st == "random": return rng.choice(["C","D"])
    if st == "tft": return th[-1] if th else "C"
    if st == "grudger": return "D" if "D" in th else "C"
    if st == "pavlov":
        if not my or not th: return "C"
        return "C" if my[-1]==th[-1] else "D"
    return "C"

def rec_pd(c, oid, mine, theirs):
    c["pdh"].setdefault(oid,[]).append(theirs)
    c["pdm"].setdefault(oid,[]).append(mine)
    for k in ["pdh","pdm"]:
        if len(c[k].get(oid,[])) > 20:
            c[k][oid] = c[k][oid][-20:]

def surp(c):
    r, sf = c["r"], c["p"]["safe"]
    return {"o2": max(0, r["o2"]-O2_EAT*sf),
            "h2o": max(0, r["h2o"]-H2O_EAT*sf),
            "food": max(0, r["food"]-FOOD_EAT*sf)}

def need(c, crit=10):
    r = c["r"]
    return {"o2": max(0, O2_EAT*crit - r["o2"]),
            "h2o": max(0, H2O_EAT*crit - r["h2o"]),
            "food": max(0, FOOD_EAT*crit - r["food"])}

def trade(cols, sol, rng):
    alive = {k:v for k,v in cols.items() if v["alive"]}
    trades = []
    for ai in sorted(alive):
        for bi in sorted(alive):
            if ai >= bi: continue
            a, b = alive[ai], alive[bi]
            d = math.hypot(a["site"]["x"]-b["site"]["x"],
                           a["site"]["y"]-b["site"]["y"])
            if d > COMM_RANGE: continue
            ma, mb = pd(a, bi, rng), pd(b, ai, rng)
            rec_pd(a, bi, ma, mb); rec_pd(b, ai, mb, ma)
            if ma != "C" or mb != "C": continue
            loss = min(0.4, d * TRANSPORT_LOSS)
            sa, sb, na, nb = surp(a), surp(b), need(a), need(b)
            for res in ["o2","h2o","food"]:
                amt = min(sa[res]*MAX_EXPORT, nb[res])
                if amt > 1:
                    a["r"][res] -= amt; b["r"][res] += amt*(1-loss)
                    a["rep"] += REP_TRADE; b["rep"] += REP_TRADE
                    a["tc"] += 1; b["tc"] += 1
                    trades.append({"sol":sol,"f":ai,"t":bi,"r":res,"a":round(amt,1)})
                amt = min(sb[res]*MAX_EXPORT, na[res])
                if amt > 1:
                    b["r"][res] -= amt; a["r"][res] += amt*(1-loss)
                    a["rep"] += REP_TRADE; b["rep"] += REP_TRADE
                    a["tc"] += 1; b["tc"] += 1
                    trades.append({"sol":sol,"f":bi,"t":ai,"r":res,"a":round(amt,1)})
    return trades

def sabotage(cols, sol, rng):
    alive = [c for c in cols.values() if c["alive"]]
    for c in alive:
        if c["p"]["aggro"] <= 0 or rng.random() > c["p"]["aggro"]: continue
        tgts = [t for t in alive if t["id"]!=c["id"]
                and math.hypot(c["site"]["x"]-t["site"]["x"],
                               c["site"]["y"]-t["site"]["y"]) <= COMM_RANGE]
        if not tgts: continue
        t = rng.choice(tgts)
        fk = rng.choice(["wf","ff","sf"])
        dmg = rng.uniform(0.02, 0.06)
        t["site"][fk] = max(0.3, t["site"][fk] - dmg)
        c["rep"] += REP_SABOTAGE; c["sc"] += 1
        if rng.random() < 0.45:
            for x in alive:
                if x["id"] != c["id"]:
                    x["pdh"].setdefault(c["id"],[]).append("D")

def sup_drop(cols, sol, rng):
    if sol % DROP_EVERY != 0 or sol == 0: return
    alive = [c for c in cols.values() if c["alive"]]
    if not alive: return
    cx = sum(c["site"]["x"] for c in alive)/len(alive)
    cy = sum(c["site"]["y"] for c in alive)/len(alive)
    dx, dy = cx+rng.uniform(-80,80), cy+rng.uniform(-80,80)
    w = min(alive, key=lambda c: (math.hypot(c["site"]["x"]-dx, c["site"]["y"]-dy), -c["rep"]))
    rmap = {"o2":"o2","h2o":"h2o","food":"food","pwr":"pwr"}
    for k,v in DROP.items(): w["r"][rmap[k]] += v
    w["drops"] += 1

def run(govs=None, maxs=500, seed=42):
    rng = random.Random(seed)
    if govs is None:
        govs = [{"id":f"col-{a}","arch":a}
                for a in ["philosopher","coder","contrarian","researcher","welcomer"]]
    sites = gen_sites(len(govs), rng)
    cols = {g["id"]: mk_col(g["id"], g["arch"], s) for g, s in zip(govs, sites)}
    tt, ts = 0, 0
    for sol in range(1, maxs+1):
        alive = [c for c in cols.values() if c["alive"]]
        if not alive: break
        for c in alive: do_produce(c); do_consume(c)
        tt += len(trade(cols, sol, rng))
        sabotage(cols, sol, rng)
        sup_drop(cols, sol, rng)
        for c in alive: chk_death(c, sol)
    return _res(cols, maxs, seed, tt)

def _res(cols, maxs, seed, tt):
    board = []
    for cid, c in cols.items():
        sv = c["dsol"] or maxs
        if c["alive"]: sv = maxs
        sc = sv*100 + c["rep"]*10 + c["tc"]*3
        ty = "water" if c["site"]["wf"]>c["site"]["ff"]+0.2 else "food" if c["site"]["ff"]>c["site"]["wf"]+0.2 else "balanced"
        board.append({"rank":0, "col":cid, "arch":c["arch"],
                       "strat":c["p"]["strat"], "type":ty,
                       "sols":sv, "alive":c["alive"], "score":round(sc),
                       "rep":round(c["rep"],1), "tr":c["tc"],
                       "sab":c["sc"], "drops":c["drops"], "cod":c["cod"],
                       "site": f'w={c["site"]["wf"]} f={c["site"]["ff"]} s={c["site"]["sf"]}'})
    board.sort(key=lambda e: -e["score"])
    for i,e in enumerate(board): e["rank"] = i+1
    coops = [c for c in cols.values() if c["p"]["strat"] in ("tft","cooperate","pavlov")]
    defs  = [c for c in cols.values() if c["p"]["strat"] in ("defect","random")]
    cs = [(c["dsol"] or maxs) for c in coops] or [0]
    ds = [(c["dsol"] or maxs) for c in defs] or [0]
    return {"board": board, "seed": seed, "maxs": maxs,
            "gt": {"trades":tt, "coop_avg":round(sum(cs)/max(len(cs),1)),
                   "def_avg":round(sum(ds)/max(len(ds),1)),
                   "coop_wins": sum(cs)/max(len(cs),1) > sum(ds)/max(len(ds),1)}}

def show(r):
    gt = r["gt"]
    print("="*76)
    print("  MARS BARN PHASE 4 — MULTI-COLONY v5 (Economy Fix + PD)")
    print(f"  {r['maxs']} sols | {len(r['board'])} colonies | seed={r['seed']}")
    print("="*76)
    print(f"  {'#':>2} {'Colony':<20} {'Arch':<11} {'Strat':<9} {'Type':<9} "
          f"{'Sols':>5} {'Score':>6} {'Rep':>5} {'Tr':>4}")
    print("  "+"-"*74)
    for e in r["board"]:
        m = "✓" if e["alive"] else "✗"
        print(f"  {e['rank']:>2} {e['col']:<20} {e['arch']:<11} {e['strat']:<9} "
              f"{e['type']:<9} {e['sols']:>4}{m} {e['score']:>6} "
              f"{e['rep']:>+5.0f} {e['tr']:>4}")
    print(f"\n  Trades: {gt['trades']}")
    print(f"  Cooperators: avg {gt['coop_avg']} sols | Defectors: avg {gt['def_avg']} sols")
    won = "COOPERATION" if gt["coop_wins"] else "DEFECTION"
    print(f"  >>> {won} WINS <<<")
    print("="*76)

def compare(trials=20, maxs=500):
    stats = {}
    for t in range(trials):
        gs = [{"id":f"col-{a}","arch":a} for a in list(STRATS.keys())[:5]]
        r = run(govs=gs, maxs=maxs, seed=t*97)
        for e in r["board"]:
            stats.setdefault(e["arch"],[]).append(e["sols"])
    return {a: {"avg":round(sum(s)/len(s)), "min":min(s), "max":max(s),
                "strat":STRATS[a]["strat"], "full":sum(1 for x in s if x>=500)}
            for a,s in sorted(stats.items()) if s}

if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv)>1 else 5
    seed = int(sys.argv[2]) if len(sys.argv)>2 else 42
    sols = int(sys.argv[3]) if len(sys.argv)>3 else 500
    archs = list(STRATS.keys())
    govs = [{"id":f"col-{a}","arch":a} for a in archs[:n]]
    r = run(govs=govs, maxs=sols, seed=seed)
    show(r)
    if "--compare" in sys.argv:
        print("\n  20-trial comparison:\n")
        c = compare(trials=20, maxs=sols)
        print(f"  {'Arch':<12} {'Strat':<10} {'Avg':>5} {'Min':>5} {'Max':>5} {'500+':>4}")
        print("  "+"-"*42)
        for a,s in sorted(c.items(), key=lambda x:-x[1]["avg"]):
            print(f"  {a:<12} {s['strat']:<10} {s['avg']:>5} {s['min']:>5} {s['max']:>5} {s['full']:>4}")
