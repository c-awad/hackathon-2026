"""Case 4 -- the shared-storage incident (synthetic): 121 findings, one cause.

Checks the causal answer against the resource graph, rebuilds the "degraded"
GPU-hours from real placements, and asks whether the real telemetry shows the
utilization drop the causal chain asserts.
"""
import json
import pandas as pd

OFFSET = 1750862959            # price book epoch_offset
PRICE = 2.50
j = pd.read_parquet("data/prepped/jobs.parquet").set_index("id_job")
g = pd.read_parquet("data/prepped/gpus.parquet")
r = pd.read_parquet("data/synthetic/resources.parquet")
e = pd.read_parquet("data/synthetic/edges.parquet")
f = pd.json_normalize(json.load(open("data/synthetic/findings.json")))
fs = f[f.detectorId == "rules::filesystem-latency-degraded"].copy()

pvc = r[r.type == "k8s:persistentvolumeclaim"].iloc[0]
print("volume:", pvc["name"], pvc["metadata"])
print("findings:", len(fs), "distinct nodes:", fs["metadata.node"].nunique(),
      "root causes:", fs.rootCauses.map(tuple).nunique(), "->", fs.rootCauses.iloc[0][0] == pvc["id"])

# Graph: MOUNTS goes pod -> volume. Where do those pods run?
mounts = e[e.edgeType == "MOUNTS"]
pods = set(mounts.sourceId)
runs = e[(e.edgeType == "RUNS_ON") & e.sourceId.isin(pods)]
name = r.set_index("id")["name"]
mount_nodes = set(name.reindex(runs.destinationId))
fnodes = set(fs["metadata.node"])
print(f"MOUNTS edges {len(mounts)} from {len(pods)} pods on {len(mount_nodes)} nodes; "
      f"finding nodes {len(fnodes)}; finding nodes that mount it {len(fnodes & mount_nodes)}; "
      f"mounting nodes with no finding {len(mount_nodes - fnodes)}")

# Time: detections span ~30 min. Find the 48 h window that reproduces impact.
t0 = pd.Timestamp(fs.detectionTime.min()).timestamp() - OFFSET
t1 = pd.Timestamp(fs.detectionTime.max()).timestamp() - OFFSET
print("detection", fs.detectionTime.min(), "->", fs.detectionTime.max())
g["start"] = g.id_job.map(j.time_start)
g["end"] = g.id_job.map(j.time_end)

def overlap_h(lo, hi, nodes):
    x = g[g.Node.isin(nodes)]
    ov = (x.end.clip(upper=hi) - x.start.clip(lower=lo)).clip(lower=0) / 3600
    return ov.groupby(x.Node).sum()

imp = fs.set_index("metadata.node")["metadata.impact_gpu_hours"]
for label, lo, hi in (("[det, det+48h]", t0, t0 + 48 * 3600),
                      ("[det-48h, det]", t0 - 48 * 3600, t0),
                      ("[det-24h, det+24h]", t0 - 24 * 3600, t0 + 24 * 3600)):
    ov = overlap_h(lo, hi, fnodes).reindex(imp.index).fillna(0)
    print(f"  {label:20s} card-h {ov.sum():8,.0f}   corr with impact {ov.corr(imp):.3f}"
          f"   median |diff| {(ov - imp).abs().median():.2f}")
WIN = (t0 - 48 * 3600, t0)   # the episode ends at detection; see the fit above

# Real telemetry: during the window, were jobs on the 121 nodes any different
# from jobs on the other nodes, or from the same nodes the week before?
def cohort(lo, hi, nodes):
    x = g[g.Node.isin(nodes) & (g.start < hi) & (g.end > lo)]
    jobs = j.loc[x.id_job.unique()]
    h = x.totalexecutiontime_sec.clip(upper=x.id_job.map(j.walltime_sec)) / 3600
    return dict(cards=len(x), jobs=len(jobs),
                util=round((x.smutilization_pct_avg * h).sum() / max(h.sum(), 1e-9), 1),
                fail=round((jobs.state_name == "FAILED").mean(), 3),
                timeout=round((jobs.state_name == "TIMEOUT").mean(), 3),
                watts=round(x.powerusage_watts_avg.median(), 1))
others = set(g.Node) - fnodes
rows = {
    "121 nodes, incident window": cohort(*WIN, fnodes),
    "other nodes, incident window": cohort(*WIN, others),
    "121 nodes, week before": cohort(WIN[0] - 7 * 86400, WIN[1] - 7 * 86400, fnodes),
    "121 nodes, week after": cohort(WIN[0] + 7 * 86400, WIN[1] + 7 * 86400, fnodes),
}
rows["38 mounting nodes w/o finding, window"] = cohort(*WIN, mount_nodes - fnodes)
print("\nreal telemetry comparison")
print(pd.DataFrame(rows).T.to_string())

# jobs *entirely inside* the window on the incident nodes: most exposed
x = g[g.Node.isin(fnodes) & (g.start >= WIN[0]) & (g.end <= WIN[1])]
print(f"\njobs wholly inside window on incident nodes: {x.id_job.nunique()}")
print(f"degraded GPU-h: finding impact {imp.sum():,.0f} (${imp.sum()*PRICE:,.0f}); "
      f"capacity of 121 nodes over 48 h {121*2*48:,}")

# The drain question: what would draining the 121 nodes cost?
cap = 121 * 2 * 48
print(f"drain all 121 nodes for 48 h: {cap:,} GPU-h (${cap*PRICE:,.0f}) of capacity removed, "
      f"{121/225:.0%} of the cluster; real work on them in the window: "
      f"{overlap_h(*WIN, fnodes).sum():,.0f} GPU-h")

# The 38 nodes that mount the volume but carry no finding: were they mounting it
# during the window? If the volume were the cause, they should be affected too.
mp = runs.assign(node=name.reindex(runs.destinationId).values,
                 job=r.set_index("id")["resourceId"].reindex(runs.sourceId).values)
mp["job"] = pd.to_numeric(mp.job, errors="coerce")
mp["start"] = mp.job.map(j.time_start); mp["end"] = mp.job.map(j.time_end)
inwin = mp[(mp.start < WIN[1]) & (mp.end > WIN[0])]
print(f"\nmounting pods active in window: {inwin.job.nunique()} on {inwin.node.nunique()} nodes; "
      f"of those nodes, without a finding: {len(set(inwin.node) - fnodes)}")
print(f"mounting pods' time span: {pd.to_datetime(mp.start.min()+OFFSET, unit='s')} -> "
      f"{pd.to_datetime(mp.end.max()+OFFSET, unit='s')}")
extra = overlap_h(*WIN, mount_nodes - fnodes).sum()
print(f"card-h in window on the 38 mounting nodes without a finding: {extra:,.0f}; "
      f"121 + 38 total {overlap_h(*WIN, mount_nodes).sum():,.0f}")
ratio = fs["metadata.fs_latency_p99_ratio"]
print(f"per-node p99 latency ratio: {ratio.min()}x-{ratio.max()}x; /v1/causal quotes the ratio of whichever finding you ask about")
