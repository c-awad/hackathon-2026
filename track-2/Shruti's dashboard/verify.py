"""Check data.json against every field app.js reads, and print what the page shows.

The IDE browser cannot reach localhost, so this stands in for a render test: a
missing or null field is exactly what would surface as "undefined" or "NaN".
"""
import json
import math
import os
import sys

PATH = os.path.join(os.path.dirname(__file__), "data.json")
d = json.load(open(PATH))
bad = []
BUCKETS = ("never_used", "barely_used", "cpu_work", "idle_card", "killed_by_clock", "productive")


def need(obj, path, *keys):
    for k in keys:
        if not isinstance(obj, dict) or k not in obj:
            bad.append(f"missing {path}.{k}")
            continue
        v = obj[k]
        if v is None:
            bad.append(f"null {path}.{k}")
        elif isinstance(v, float) and math.isnan(v):
            bad.append(f"NaN {path}.{k}")


need(d, "", "meta", "spine", "tile1", "tile2", "tile3")

m = d["meta"]
need(m, "meta", "title", "subtitle", "cluster", "price_book", "sources", "rules_recomputed", "caveat")
need(m["cluster"], "meta.cluster", "nodes", "gpus_per_node", "jobs", "users", "gpu_hours")
need(m["price_book"], "meta.price_book", "usd_per_gpu_hour", "version")
need(m["rules_recomputed"]["gpu-imbalance"], "meta.rules_recomputed.gpu-imbalance", "jobs", "idle_gpu_hours")

# ------------------------------------------------------------------ the spine
# app.js colours rows by key, so an unknown key would render grey and silently
# break the thread running through the three tiles.
keys = [b["key"] for b in d["spine"]]
if set(keys) != set(BUCKETS):
    bad.append(f"spine keys {keys} do not match the six the page colours")
for b in d["spine"]:
    need(b, "spine[]", "key", "name", "full_name", "plain", "now", "cut", "tradeoff")
    # the tabs show `name`, so it has to stay short enough to sit in a legend row
    if len(b["name"]) > 26:
        bad.append(f"spine.{b['key']} name is {len(b['name'])} chars, too long for a legend")
    need(b["now"], f"spine.{b['key']}.now", "jobs", "gpu_hours", "usd", "share_of_bill", "busy_pct", "note")
    need(b["cut"], f"spine.{b['key']}.cut", "gpu_hours", "usd", "share_of_bucket", "share_of_bill",
         "basis", "action", "owner", "confidence")
    need(b["tradeoff"], f"spine.{b['key']}.tradeoff", "risk", "what_breaks", "cost_gpu_hours",
         "cost_usd", "defence")
    if b["cut"]["gpu_hours"] > b["now"]["gpu_hours"] + 1:
        bad.append(f"spine.{b['key']} cuts more than the bucket holds")

t1, t2, t3 = d["tile1"], d["tile2"], d["tile3"]

# Every tab leads with exactly three plain numbers. More than that is the overload
# the report exists to absorb.
for name, tile in (("tile1", t1), ("tile2", t2), ("tile3", t3)):
    need(tile, name, "kpis")
    if len(tile.get("kpis", [])) != 3:
        bad.append(f"{name} has {len(tile.get('kpis', []))} headline numbers, the strip shows 3")
    for k in tile.get("kpis", []):
        need(k, f"{name}.kpis[]", "value", "label", "sub")

need(t1, "tile1", "title", "question", "headline", "funnel", "by_outcome", "concentration", "reading")
need(t1["headline"], "tile1.headline", "usd", "gpu_hours", "jobs", "users", "months", "statement")
for s in t1["funnel"]:
    need(s, "tile1.funnel[]", "label", "gpu_hours", "usd", "cents", "note")
if len(t1["funnel"]) != 3:
    bad.append(f"tile1.funnel has {len(t1['funnel'])} stages, the chart draws 3")
fh = [s["gpu_hours"] for s in t1["funnel"]]
if not (fh[0] >= fh[1] >= fh[2]):
    bad.append(f"funnel stages are not descending: {fh}")
for o in t1["by_outcome"]:
    need(o, "tile1.by_outcome[]", "outcome", "jobs", "gpu_hours", "usd", "share", "busy_pct")

conc = t1["concentration"]
need(conc, "tile1.concentration", "curve", "markers", "users_total")
for p in conc["curve"]:
    need(p, "tile1.concentration.curve[]", "users", "share")
shares = [p["share"] for p in conc["curve"]]
if shares[0] != 0 or abs(shares[-1] - 1.0) > 0.01:
    bad.append(f"concentration curve runs {shares[0]} to {shares[-1]}, expected 0 to 1")
if any(b2 < a - 1e-9 for a, b2 in zip(shares, shares[1:])):
    bad.append("concentration curve is not monotonic")
if conc["curve"][-1]["users"] != conc["users_total"]:
    bad.append("concentration curve does not end at the last researcher")
for mk in conc["markers"]:
    need(mk, "tile1.concentration.markers[]", "users", "share")

need(t2, "tile2", "title", "question", "total", "target", "verdict", "grace_sweep", "ranked",
     "wheel", "reading")

# The cut wheel must be the tile 1 wheel with slices removed: same per-bucket angles,
# cut shares summing to the point estimate, and nothing cut below zero.
w = t2["wheel"]
need(w, "tile2.wheel", "before_usd", "before_gpu_hours", "cut_usd", "cut_gpu_hours",
     "after_usd", "after_gpu_hours", "cut_share", "segments")
if len(w["segments"]) != len(d["spine"]):
    bad.append(f"wheel has {len(w['segments'])} segments, the spine has {len(d['spine'])}")
spine_by_key = {b["key"]: b for b in d["spine"]}
for s in w["segments"]:
    need(s, "tile2.wheel.segments[]", "key", "name", "share_of_bill", "cut_share_of_bill",
         "kept_share_of_bill", "cut_usd", "kept_usd")
    b = spine_by_key.get(s["key"])
    if b is None:
        bad.append(f"wheel segment {s['key']} is not a spine bucket")
        continue
    if abs(s["share_of_bill"] - b["now"]["share_of_bill"]) > 1e-6:
        bad.append(f"wheel segment {s['key']} changed size from tile 1")
    if abs(s["kept_share_of_bill"] + s["cut_share_of_bill"] - s["share_of_bill"]) > 2e-4:
        bad.append(f"wheel segment {s['key']}: kept + cut != the whole slice")
    if s["kept_share_of_bill"] < -1e-9 or s["cut_share_of_bill"] < -1e-9:
        bad.append(f"wheel segment {s['key']} has a negative arc")
if abs(sum(s["share_of_bill"] for s in w["segments"]) - 1.0) > 2e-3:
    bad.append("wheel slices do not close the circle")
if abs(sum(s["cut_share_of_bill"] for s in w["segments"]) - w["cut_share"]) > 2e-4:
    bad.append("wheel cut slices do not sum to the headline cut share")
if abs(w["before_gpu_hours"] - w["cut_gpu_hours"] - w["after_gpu_hours"]) > 2:
    bad.append("wheel centre arithmetic: before - cut != after")
if abs(w["cut_gpu_hours"] - t2["total"]["point"]["gpu_hours"]) > 2:
    bad.append("wheel cut does not match tile 2's point estimate")
for k in ("low", "point", "high"):
    need(t2["total"][k], f"tile2.total.{k}", "gpu_hours", "usd", "share", "basis")
need(t2["target"], "tile2.target", "gpu_hours", "usd")
need(t2["grace_sweep"], "tile2.grace_sweep", "hours", "gpu_hours", "note")
for gr in t2["grace_sweep"]["hours"]:
    if str(gr) not in t2["grace_sweep"]["gpu_hours"]:
        bad.append(f"grace_sweep missing the {gr}h entry the chart plots")
for r in t2["ranked"]:
    need(r, "tile2.ranked[]", "rank", "key", "name", "usd", "gpu_hours", "action", "owner",
         "confidence", "risk")
    if r["key"] not in BUCKETS:
        bad.append(f"tile2.ranked references unknown bucket {r['key']}")

need(t3, "tile3", "title", "question", "risks", "simulator", "definitions", "nodes", "limits", "reading")

# Tile 3 is a short list of calls. Each level has to have a matching styles.css rule,
# or the row loses its colour and reads as neutral.
LEVELS = {"safe", "risky", "needs people", "not a saving"}
for r in t3["risks"]:
    need(r, "tile3.risks[]", "claim", "level", "amount", "what_if_wrong")
    if r["level"] not in LEVELS:
        bad.append(f"tile3 risk level {r['level']!r} has no .level-* rule in styles.css")
if len(t3["risks"]) > 5:
    bad.append(f"tile3 lists {len(t3['risks'])} calls; more than 5 is a table, not a verdict")

s = t3["simulator"]
need(s, "tile3.simulator", "graces", "thresholds", "guards", "grid", "default", "note")
need(s["default"], "tile3.simulator.default", "g", "t", "guard")
for gd in s["guards"]:
    need(gd, "tile3.simulator.guards[]", "key", "label", "hint")
CELL = ("g", "t", "guard", "jobs", "returns_gpu_hours", "returns_usd", "busy_destroyed_gpu_hours",
        "busy_destroyed_usd", "completed_jobs_hit", "bursty_jobs_hit", "bursty_gpu_hours_hit")
for c in s["grid"]:
    need(c, "tile3.simulator.grid[]", *CELL)

index = {(c["g"], c["t"], c["guard"]): c for c in s["grid"]}
expected = len(s["graces"]) * len(s["thresholds"]) * len(s["guards"])
if len(index) != expected:
    bad.append(f"grid has {len(index)} cells, expected {expected}")
for gi in range(len(s["graces"])):
    if (gi, 0, "peak0") not in index:
        bad.append(f"missing baseline cell {gi}|0|peak0 the verdict compares against")

for x in t3["definitions"]:
    need(x, "tile3.definitions[]", "question", "options", "why")
    for o in x["options"]:
        need(o, "tile3.definitions[].options[]", "label", "verdict")
        if "gpu_hours" in o:
            need(o, "tile3.definitions[].options[]", "usd")
        elif "pct" not in o:
            bad.append(f"definition {x['id']} option has neither gpu_hours nor pct")
    if x.get("cost_usd") is not None:
        need(x, "tile3.definitions[]", "cost_gpu_hours")

n = t3["nodes"]
need(n, "tile3.nodes", "exposure", "cluster_failure_rate", "by_count", "by_rate",
     "ranking_overlap", "drain_cost", "why")
need(n["drain_cost"], "tile3.nodes.drain_cost", "gpu_hours", "usd")
need(n["exposure"], "tile3.nodes.exposure", "min_jobs", "max_jobs", "exposure_floor")
for r in n["by_count"] + n["by_rate"]:
    need(r, "tile3.nodes.rows[]", "node", "jobs", "failures", "failure_rate", "gpu_hours_served",
         "one_owner_dominates")
    if r["top_owner_share_of_failures"] is None and r["failures"] > 0:
        bad.append(f"node {r['node']} has failures but no owner share")
for l in t3["limits"]:
    need(l, "tile3.limits[]", "limit", "consequence")


def usd(x):
    a = abs(x)
    if a >= 1e6:
        return f"${x/1e6:.2f}M"
    if a >= 1e3:
        return f"${round(x/1e3):,.0f}K"
    return f"${x:,.0f}"


# ------------------------------------------------------------ what a tab shows
print("what each tab shows\n")
for name, tile in (("1 " + t1["title"], t1), ("2 " + t2["title"], t2), ("3 " + t3["title"], t3)):
    print(f"  tab {name}")
    for k in tile["kpis"]:
        print(f"    {k['value']:>8}  {k['label']}")
print()
for r in t3["risks"]:
    print(f"  [{r['level']:^14}] {r['amount']:>7}  {r['claim']}")

# ----------------------------------------------------- the spine, read 3 ways
print("\nthe spine, as the report shows it\n")
print(f"{'bucket':<34} {'tile 1 now':>12} {'tile 2 cut':>12} {'tile 3 at stake':>16}  risk")
order = {k: i for i, k in enumerate(BUCKETS)}
for b in sorted(d["spine"], key=lambda x: order[x["key"]]):
    print(f"{b['name'][:33]:<34} {usd(b['now']['usd']):>12} "
          f"{(usd(b['cut']['usd']) if b['cut']['usd'] else '--'):>12} "
          f"{(usd(b['tradeoff']['cost_usd']) if b['tradeoff']['cost_usd'] else '--'):>16}  "
          f"{b['tradeoff']['risk']}")

tot_now = sum(b["now"]["gpu_hours"] for b in d["spine"])
tot_cut = sum(b["cut"]["gpu_hours"] for b in d["spine"])
print(f"\n{'TOTAL':<34} {usd(tot_now * 2.5):>12} {usd(tot_cut * 2.5):>12}")
if abs(tot_now - d["meta"]["cluster"]["gpu_hours"]) > 2:
    bad.append(f"spine sums to {tot_now:,.0f} GPU-h, not the bill's {d['meta']['cluster']['gpu_hours']:,.0f}")
if abs(tot_cut - t2["total"]["point"]["gpu_hours"]) > 2:
    bad.append(f"cut column sums to {tot_cut:,.0f}, not tile 2's point estimate "
               f"{t2['total']['point']['gpu_hours']:,.0f}")

# ------------------------------------------------------- the simulator readout
print(f"\n{'grace':>7} {'unused below':>13} {'guard':>7} | {'frees':>9} {'destroys':>9} "
      f"{'jobs':>7} {'bursty':>7}")
for gi, ti, guard in [(2, 0, "peak0"), (0, 0, "peak0"), (7, 0, "peak0"),
                      (2, 0, "none"), (2, 3, "none"), (2, 5, "none")]:
    c = index[(gi, ti, guard)]
    print(f"{s['graces'][gi]:>7} {s['thresholds'][ti]:>12}% {guard:>7} | "
          f"{usd(c['returns_usd']):>9} {usd(c['busy_destroyed_usd']):>9} "
          f"{c['jobs']:>7,} {c['bursty_jobs_hit']:>7,}")

for ti in range(len(s["thresholds"])):
    for gd in s["guards"]:
        seq = [index[(gi, ti, gd["key"])]["returns_gpu_hours"] for gi in range(len(s["graces"]))]
        if any(b2 - a > 1 for a, b2 in zip(seq, seq[1:])):
            bad.append(f"returns rise with a longer grace at t={ti} guard={gd['key']}")

print()
if bad:
    print(f"{len(bad)} PROBLEM(S):")
    for b in bad:
        print("  -", b)
    sys.exit(1)
print("data.json satisfies every field app.js reads; the spine reconciles across all three tiles.")
