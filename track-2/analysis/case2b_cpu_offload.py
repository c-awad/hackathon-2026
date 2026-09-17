"""Case 2b -- which GPU jobs could run on a CPU node instead?

The data holds each job's request (cpus, memory, GPUs, time limit) but not the
program it ran, so "needs a GPU" is inferred from what the GPU did.
"""
import pandas as pd

PRICE = 2.50
j = pd.read_parquet("data/prepped/jobs.parquet")
TOTAL = j.gpu_hours.sum()

no_kernel = j.sm_util_max == 0
no_mem = j.max_gpu_mem_used == 0
tier = pd.Series("T4 used the GPU", index=j.index)
tier[(j.sm_util_max <= 10) & (j.max_gpu_mem_used < 1 * 2**30)] = "T3 barely touched (peak<=10%, <1 GiB)"
tier[no_kernel & ~no_mem] = "T2 CUDA context, no kernel"
tier[no_kernel & no_mem] = "T1 never touched the GPU"
j["tier"] = tier

def table(g):
    t = j.groupby(g, observed=True).agg(jobs=("id_job", "size"), gpu_h=("gpu_hours", "sum"),
                                        watts=("watts_avg", "median"),
                                        gib=("max_gpu_mem_used", lambda s: s.median() / 2**30))
    t["share"] = t.gpu_h / TOTAL
    t["usd"] = t.gpu_h * PRICE
    return t

print(table("tier").to_string(float_format=lambda x: f"{x:,.2f}"))

print("\ntier x outcome, GPU-h")
print(pd.crosstab(j.tier, j.state_name, values=j.gpu_hours, aggfunc="sum").round(0).fillna(0).to_string())
print("\ntier x job type, GPU-h")
print(pd.crosstab(j.tier, j.job_type, values=j.gpu_hours, aggfunc="sum").round(0).fillna(0).to_string())

cand = j[j.tier.str[:2].isin(["T1", "T2"])]
print("\nT1+T2 requests: cpus / total mem GiB / gpus (quantiles)")
print(pd.DataFrame({"cpus": cand.cpus_req, "mem_gib": cand.mem_req_total_mb / 1024,
                    "gpus": cand.gpu_count}).quantile([.5, .9, .99, 1]).round(1).to_string())
fits = (cand.cpus_req <= 40) & (cand.mem_req_total_mb <= 384 * 1024) & (cand.nodes_alloc == 1)
print(f"fit one 40-core/384 GiB node: {fits.mean():.1%} of jobs, "
      f"{cand.gpu_hours[fits].sum()/cand.gpu_hours.sum():.1%} of hours")

# Is it a habit? Per-owner share of their own GPU-hours in T1/T2.
u = j.assign(c=j.tier.str[:2].isin(["T1", "T2"]) * j.gpu_hours).groupby("id_user").agg(
    h=("gpu_hours", "sum"), c=("c", "sum"), jobs=("id_job", "size"))
u["frac"] = u.c / u.h
hab = u[(u.frac >= 0.5) & (u.jobs >= 20)]
print(f"\nowners with >=50% of their GPU-h never running a kernel (>=20 jobs): {len(hab)}"
      f" -> {hab.c.sum():,.0f} GPU-h of the {u.c.sum():,.0f} in T1+T2")
top = u.sort_values("c", ascending=False)
for k in (5, 10, 20):
    print(f"  top {k} owners hold {top.c.head(k).sum()/u.c.sum():.0%} of T1+T2 hours")

# Arrays: a whole submission that never touched the GPU is one fix.
a = cand[cand.is_array_task].groupby("id_array_job").agg(tasks=("id_job", "size"), h=("gpu_hours", "sum"))
allarr = j[j.is_array_task].groupby("id_array_job").id_job.size()
whole = a[a.tasks == allarr.reindex(a.index)]
print(f"\narrays where every task never ran a kernel: {len(whole)} arrays, {whole.tasks.sum():,} tasks,"
      f" {whole.h.sum():,.0f} GPU-h")

# Completed T1/T2 is the clean CPU-offload set: the work succeeded without a GPU.
done = cand[cand.state_name == "COMPLETED"]
print(f"\nCOMPLETED T1+T2: {len(done):,} jobs, {done.gpu_hours.sum():,.0f} GPU-h, ${done.gpu_hours.sum()*PRICE:,.0f}")
print(done.groupby("tier").gpu_hours.agg(["size", "sum"]).round(0).to_string())
print("by gpu_count\n", done.groupby("gpu_count").gpu_hours.agg(["size", "sum"]).round(0).to_string())
print("walltime h (quantiles):", (done.walltime_sec / 3600).quantile([.5, .9, .99]).round(2).to_dict())
