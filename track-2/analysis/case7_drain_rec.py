"""Case 7 -- audit the API's recommendations, above all "drain the top 5 nodes".

The endpoint ranks machines by how many findings touch them and sums those
findings' impact_gpu_hours as the saving. Neither step reads rootCauses.
"""
import json
import urllib.request
import pandas as pd

PRICE = 2.50
API = "http://localhost:8000"
recs = json.load(urllib.request.urlopen(f"{API}/v1/recommendations"))["recommendations"]
drain = next(r for r in recs if r["id"] == "rec_drain_nodes")
low = next(r for r in recs if r["id"] == "rec_lowutil")
print("drain:", drain["estimated_savings"], drain["estimated_savings_gpu_hours"], "conf", drain["confidence"])

j = pd.read_parquet("data/prepped/jobs.parquet").set_index("id_job")
r = pd.read_parquet("data/synthetic/resources.parquet")
raw = json.load(open("data/synthetic/findings.json"))
f = pd.json_normalize(raw)
name = r.set_index("id")["name"]
typ = r.set_index("id")["type"]

# Rebuild the ranking the endpoint uses: findings per node resource.
x = f[["id", "detectorId", "resourceIds", "metadata.impact_gpu_hours", "metadata.impact_kind",
       "metadata.impact_scope", "rootCauses"]].explode("resourceIds")
x = x[x.resourceIds.map(typ) == "k8s:node"]
x["node"] = x.resourceIds.map(name)
rank = x.groupby("node").agg(findings=("id", "nunique"), impact=("metadata.impact_gpu_hours", "sum"))
# The endpoint's own ranking (same counts; ties broken by dict order).
up = json.load(urllib.request.urlopen(f"{API}/v1/resources/underperforming?entity_type=node&limit=8"))["rows"]
print("\nendpoint ranking:", [(u["entity_id"], u["finding_count"], u["impact_gpu_hours"]) for u in up])
top5 = rank.loc[[u["entity_id"] for u in up[:5]]]
ties = rank[rank.findings == top5.findings.min()].index.tolist()
print("\ntop 5 by finding count:\n", top5.to_string(), "\n5th place is a tie between:", ties)
print("endpoint impact (job-scope only):", round(sum(u["impact_gpu_hours"] for u in up[:5]), 1))
print(f"impact sum {top5.impact.sum():,.1f} vs endpoint {drain['estimated_savings_gpu_hours']}")

tri = pd.read_json("analysis/out_case6_triage.json")
t5 = x[x.node.isin(top5.index)]
print("\nwhat the findings on those 5 are:")
print(t5.groupby(["node", "detectorId"]).id.nunique().unstack(fill_value=0).T.to_string())
print("\nshare of their findings that carry a rootCause elsewhere (arrays, volume):",
      round((t5.rootCauses.map(len) > 0).mean(), 3))
rc = t5[t5.rootCauses.map(len) > 0].rootCauses.map(lambda v: typ.get(v[0])).value_counts().to_dict()
print("  root-cause types:", rc)
print("impact kinds summed:", t5.groupby("metadata.impact_kind")["metadata.impact_gpu_hours"].sum().round(0).to_dict())

print("\ncase 6 verdicts for these nodes:")
print(tri[tri.node.isin(top5.index)][["node", "window", "failed", "jobs", "cause", "top_share"]].to_string())

hw_nodes = {"r216287-n200569"}
nf = j[j.hit_node_failure & j.nodefail_exact].nodefail_nodes.map(lambda v: list(v)[0])
print("\nhardware evidence on top 5: signature machine:", sorted(set(top5.index) & hw_nodes),
      "| located node failures:", nf[nf.isin(top5.index)].value_counts().to_dict())

# Where does the silent SIGBUS machine rank?
print("r216287-n200569 rank by finding count:",
      int(rank.findings.rank(ascending=False, method="min")["r216287-n200569"]), "of", len(rank))

# What draining them would cost: capacity, and what those nodes did.
g = pd.read_parquet("data/prepped/gpus.parquet")
g["card_h"] = g.totalexecutiontime_sec.clip(upper=g.id_job.map(j.walltime_sec)) / 3600
on = g[g.Node.isin(top5.index)]
days = (j.time_end.max() - j.time_start.min()) / 86400
busy = (on.card_h * on.smutilization_pct_avg / 100).sum()
succ = on[on.id_job.map(j.state_name) == "COMPLETED"].card_h.sum()
print(f"\ntop 5 delivered {on.card_h.sum():,.0f} card-h over {days:.0f} days "
      f"({on.card_h.sum()/(5*2*24*days):.0%} of their capacity), {succ:,.0f} on COMPLETED jobs, busy-weighted {busy:,.0f}")
print(f"drain cost: {5*2*24*7:,} GPU-h/week (${5*2*24*7*PRICE:,.0f}); for the rest of a quarter (13 wk) "
      f"{5*2*24*91:,} GPU-h (${5*2*24*91*PRICE:,.0f})")
fails_here = on.drop_duplicates("id_job")
fails_here = fails_here[fails_here.id_job.map(j.state_name) == "FAILED"]
owners = fails_here.id_job.map(j.id_user)
print(f"failed jobs on top 5: {len(fails_here)}; owners {owners.nunique()}; top owner share {owners.value_counts(normalize=True).iloc[0]:.0%}")
# would those owners fail elsewhere? same owners' failure rate on other nodes
other = g[~g.Node.isin(top5.index)].drop_duplicates("id_job")
other = other[other.id_job.map(j.id_user).isin(owners.unique())]
print(f"those owners' FAILED rate on every other machine: {(other.id_job.map(j.state_name)=='FAILED').mean():.1%}"
      f" vs on top 5: {len(fails_here)/on.id_job.nunique():.1%}")

# The other recommendation
lf = f[f.detectorId == "rules::gpu-low-utilization"]
print(f"\nrec_lowutil: {low['estimated_savings_gpu_hours']:,} GPU-h = 0.35 x {lf['metadata.impact_gpu_hours'].sum():,.0f}"
      f" ({len(lf)} findings, cites {len(low['finding_ids'])}); gpu_count of those jobs:",
      j.loc[lf['metadata.job_id'].astype('int64')].gpu_count.value_counts().sort_index().to_dict())
