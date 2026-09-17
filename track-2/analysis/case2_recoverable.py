"""Case 2 -- recoverable GPU-hours, deduplicated to one class per job.

Findings are used as labels only; hours come from jobs.parquet so nothing is
counted twice. Each job lands in exactly one class, first match wins.
"""
import json
import numpy as np
import pandas as pd

PRICE = 2.50
TOTAL = None

j = pd.read_parquet("data/prepped/jobs.parquet").set_index("id_job")
TOTAL = j.gpu_hours.sum()
f = pd.json_normalize(json.load(open("data/synthetic/findings.json")))

wall_h = (j.walltime_sec / 3600).clip(lower=1e-9)
never_ran = (j.sm_util_avg == 0) & (j.sm_util_max == 0)
near_idle = ~never_ran & (j.sm_util_avg < 5)

imb = f[f.detectorId == "rules::gpu-imbalance"]
imb_idle = imb.set_index(imb["metadata.job_id"].astype("int64"))["metadata.idle_gpu_hours"]
imb_idle = imb_idle.groupby(level=0).sum()
imbalanced = j.index.isin(imb_idle.index) & ~never_ran & ~near_idle

cls = pd.Series("productive_or_unclassified", index=j.index)
cls[never_ran & (j.state_name == "COMPLETED")] = "A1 never ran, completed (belongs on CPU)"
cls[never_ran & (j.state_name != "COMPLETED")] = "A2 never ran, did not complete"
cls[near_idle] = "B  near-idle (<5% avg, computed briefly)"
cls[imbalanced] = "C  card imbalance (idle cards only)"
busy_timeout = (cls == "productive_or_unclassified") & (j.state_name == "TIMEOUT") & (j.sm_util_avg >= 50)
cls[busy_timeout] = "D  busy work killed at time limit (not a cut)"

def idle_after(grace_h):
    """GPU-hours an idle-kill after `grace_h` hours would return, per job."""
    return j.gpu_hours * ((wall_h - grace_h).clip(lower=0) / wall_h)

summary = j.groupby(cls).agg(jobs=("gpu_hours", "size"), gpu_h=("gpu_hours", "sum"))
summary["share"] = summary.gpu_h / TOTAL
print(summary.to_string(float_format=lambda x: f"{x:,.3f}"))

A1 = cls.str.startswith("A1"); A2 = cls.str.startswith("A2")
B = cls.str.startswith("B"); C = cls.str.startswith("C")

print("\nA2 idle-kill sweep: GPU-h returned if a job at 0% for G hours is ended")
for g in (0, 0.5, 1, 2, 4, 8):
    print(f"  grace {g:>4}h  {idle_after(g)[A2].sum():>9,.0f} GPU-h   ${idle_after(g)[A2].sum()*PRICE:>9,.0f}")

a2_by = pd.DataFrame({"h": j.gpu_hours[A2], "ret1h": idle_after(1)[A2],
                      "state": j.state_name[A2], "type": j.job_type[A2]})
print("\nA2 by outcome (grace 1h)\n", a2_by.groupby("state")[["h", "ret1h"]].sum().round(0).to_string())
print("\nA2 by job type (grace 1h)\n", a2_by.groupby("type")[["h", "ret1h"]].sum().round(0).to_string())

b_idle = (j.gpu_hours * (1 - j.sm_util_avg / 100))[B]
c_idle = imb_idle.reindex(j.index[C]).fillna(0)
print(f"\nA1 full hours           {j.gpu_hours[A1].sum():>9,.0f}")
print(f"B  idle share of hours  {b_idle.sum():>9,.0f}  (of {j.gpu_hours[B].sum():,.0f})")
print(f"C  idle-card hours      {c_idle.sum():>9,.0f}")

# --- the cost of being wrong for an idle-kill policy ------------------------
# No intra-job time series, so the risk proxy is jobs that averaged ~0 but
# peaked high: they did real work in a short burst, and a naive "low average"
# policy would have killed them.
burst = (j.sm_util_avg < 5) & (j.sm_util_max >= 50)
print(f"\nrisk proxy: avg<5% but peak>=50%: {burst.sum():,} jobs, {j.gpu_hours[burst].sum():,.0f} GPU-h,"
      f" {j[burst].state_name.eq('COMPLETED').mean():.0%} completed")

# --- CANCELLED --------------------------------------------------------------
c = j.state_name == "CANCELLED"
print("\nCANCELLED by class, GPU-h")
print(j[c].groupby(cls[c]).gpu_hours.sum().round(0).to_string())
print("CANCELLED hour-weighted util:", round((j.gpu_hours*j.sm_util_avg)[c].sum()/j.gpu_hours[c].sum(), 1))

# --- the claim --------------------------------------------------------------
low = j.gpu_hours[A1].sum() * 0.5 + idle_after(4)[A2].sum()
point = j.gpu_hours[A1].sum() + idle_after(1)[A2].sum() + 0.5 * b_idle.sum() + 0.5 * c_idle.sum()
high = j.gpu_hours[A1].sum() + idle_after(0)[A2].sum() + b_idle.sum() + c_idle.sum()
for name, v in (("low", low), ("point", point), ("high", high)):
    print(f"{name:>5}: {v:>9,.0f} GPU-h  {v/TOTAL:5.1%}  ${v*PRICE:>9,.0f}")
print(f"20% target: {0.2*TOTAL:,.0f} GPU-h  ${0.2*TOTAL*PRICE:,.0f}")
