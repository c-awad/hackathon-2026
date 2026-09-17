"""Case 3 -- card imbalance: multi-GPU jobs where some cards idle while others work.

jobs.parquet averages the cards, so this needs gpus.parquet (one row per card per
job). Per-card durations are clipped to the job's wall time (docs/data.md: 66 rows
report more runtime than their job had).
"""
import json
import pandas as pd

PRICE = 2.50
j = pd.read_parquet("data/prepped/jobs.parquet").set_index("id_job")
g = pd.read_parquet("data/prepped/gpus.parquet")
g = g[g.id_job.map(j.gpu_count) >= 2].copy()
g["wall"] = g.id_job.map(j.walltime_sec)
g["card_h"] = g.totalexecutiontime_sec.clip(upper=g.wall) / 3600
g["sm"] = g.smutilization_pct_avg
g["sm_max"] = g.smutilization_pct_max
g["attempts"] = g.id_job.map(j.attempts)

per = g.groupby("id_job").agg(cards=("gpu_id", "size"), nodes=("Node", "nunique"),
                               busiest=("sm", "max"), quietest=("sm", "min"),
                               card_h=("card_h", "sum"), wall=("wall", "first"),
                               attempts=("attempts", "first"))
per["spread"] = per.busiest - per.quietest
print(f"multi-card jobs {len(per):,}   card-hours {per.card_h.sum():,.0f}"
      f"   (unclipped {g.totalexecutiontime_sec.sum()/3600:,.0f})")
print(f"requeued multi-card jobs (rows may mix attempts): {(per.attempts > 1).sum()}")

# 1. Reproduce the rule: >=2 cards, busiest >= 20, spread > 30, walltime > 1 h.
rule = (per.busiest >= 20) & (per.spread > 30) & (per.wall > 3600)
f = pd.json_normalize(json.load(open("data/synthetic/findings.json")))
fi = f[f.detectorId == "rules::gpu-imbalance"]
fjobs = set(fi["metadata.job_id"].astype("int64"))
print(f"\nrule reproduced: {rule.sum()} jobs; finding has {len(fjobs)}; overlap {len(fjobs & set(per.index[rule]))}")
print(f"finding idle_gpu_hours sum {fi['metadata.idle_gpu_hours'].sum():,.0f}   impact sum {fi['metadata.impact_gpu_hours'].sum():,.0f}")
print("finding sample metadata:\n", fi[[c for c in fi.columns if c.startswith('metadata.')]].dropna(axis=1).head(3).T.to_string())

# 2. Idle-card hours under different definitions. A card only counts when
#    another card in the same job was working (busiest >= 20), so jobs where
#    every card idled -- case 2's never-ran -- are excluded.
g = g.join(per[["busiest", "spread", "wall"]].rename(columns={"wall": "jwall"}), on="id_job")
working = (g.busiest >= 20) & (g.jwall > 3600)
defs = {
    "strict: card peak 0% (never ran a kernel)":   working & (g.sm_max == 0),
    "card avg 0%":                                   working & (g.sm == 0),
    "card avg < 5%":                                 working & (g.sm < 5),
    "rule-like: card >30 pts below busiest":         working & (g.busiest - g.sm > 30),
}
print("\nidle-card GPU-h, by definition")
for k, m in defs.items():
    print(f"  {k:45s} cards={m.sum():5d} jobs={g[m].id_job.nunique():5d} {g.card_h[m].sum():>9,.0f} GPU-h  ${g.card_h[m].sum()*PRICE:>9,.0f}")
# relative shortfall: hours the card would have delivered at the busiest card's rate
short = (((g.busiest - g.sm) / 100) * g.card_h)[working & (g.busiest - g.sm > 30)]
print(f"  {'shortfall vs busiest card (rate-weighted)':45s} {'':22s} {short.sum():>9,.0f} GPU-h")

# 3. Which card idles? If code only uses the default device, it is gpu_id 1
#    on a 2-card node (device 0 is the default).
idle = defs["card avg < 5%"]
print("\nidle cards by gpu_id:", g[idle].gpu_id.value_counts().to_dict(),
      " hours:", g[idle].groupby("gpu_id").card_h.sum().round(0).to_dict())
print("all multi-card rows by gpu_id:", g.gpu_id.value_counts().to_dict())
two = per[(per.cards == 2) & (per.nodes == 1)].index
g2 = g[g.id_job.isin(two)].pivot_table(index="id_job", columns="gpu_id", values="sm")
g2 = g2.dropna()
lop = g2[(g2.max(axis=1) >= 20) & ((g2[0] - g2[1]).abs() > 30)]
print(f"single-node 2-card jobs with imbalance: {len(lop)};  card0 busy/card1 idle: {(lop[0] > lop[1]).sum()}"
      f";  card1 busy/card0 idle: {(lop[1] > lop[0]).sum()}")
# on multi-node jobs: is it one working card per node, or one working node?
mn = per[(per.nodes > 1)].index
gm = g[g.id_job.isin(mn) & working]
node_view = gm.groupby(["id_job", "Node"]).sm.agg(["max", "min"])
node_view["idle_card_on_busy_node"] = (node_view["max"] >= 20) & (node_view["min"] < 5)
jobv = node_view.groupby("id_job").agg(nodes=("max", "size"), busy_nodes=("max", lambda s: (s >= 20).sum()),
                                       half_idle_nodes=("idle_card_on_busy_node", "sum"))
print(f"multi-node working jobs: {len(jobv)}; all nodes busy but one card idle on each: "
      f"{((jobv.half_idle_nodes == jobv.nodes)).sum()}; only some nodes busy: {(jobv.busy_nodes < jobv.nodes).sum()}")

# 4. Who and what
ij = g[idle].groupby("id_job").card_h.sum()
jj = j.loc[ij.index]
print("\nidle-card hours by width:", ij.groupby(jj.gpu_count).sum().round(0).to_dict())
print("by outcome:", ij.groupby(jj.state_name).sum().round(0).to_dict())
print("by job type:", ij.groupby(jj.job_type).sum().round(0).to_dict())
u = ij.groupby(jj.id_user).sum().sort_values(ascending=False)
print(f"owners: {len(u)}; top 5 hold {u.head(5).sum()/u.sum():.0%}, top 10 {u.head(10).sum()/u.sum():.0%}")
arr = jj.is_array_task.mean()
print(f"array tasks among imbalanced jobs: {arr:.0%}")
# repeat offenders: owners whose multi-card jobs are *mostly* imbalanced
mc = per.join(j[["id_user"]])
mc["imb"] = mc.index.isin(ij.index)
o = mc.groupby("id_user").agg(jobs=("imb", "size"), imb=("imb", "mean"))
print(f"owners with >=10 multi-card jobs, >=80% imbalanced: {((o.jobs >= 10) & (o.imb >= .8)).sum()},"
      f" holding {u[o[(o.jobs >= 10) & (o.imb >= .8)].index.intersection(u.index)].sum():,.0f} idle-card GPU-h")
