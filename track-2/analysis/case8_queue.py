"""Case 8 -- the queue tail, and what waiting is worth.

wait_sec = time_start - time_submit. It splits into time before the job was even
eligible (held, dependencies, begin-time) and real queue time
(time_start - time_eligible). Engineer-hours are counted per person, with
overlapping waits merged: someone with 200 array tasks pending waits once.
"""
import json
import urllib.request
import numpy as np
import pandas as pd

OFFSET = 1750862959
USD_ENG = 95.0
USD_GPU = 2.50
TARGET = 4 * 3600
j = pd.read_parquet("data/prepped/jobs.parquet")
j = j[j.time_start.notna()].copy()
j["pre"] = j.time_eligible - j.time_submit
j["qw"] = j.time_start - j.time_eligible
H = 3600

# ---- A. what the API says ---------------------------------------------------
q = json.load(urllib.request.urlopen("http://localhost:8000/v1/queue/latency"))
row = q["rows"][0]
print(f"API: p50 {row['p50_sec']:.0f}s p90 {row['p90_sec']/H:.1f}h p99 {row['p99_sec']/H:.1f}h max {row['max_sec']/86400:.1f}d;"
      f" total {row['total_wait_hours']:,.0f} h -> ${q['monetized']['amount']:,.0f}")
print(f"  that is {q['monetized']['amount'] / (j.gpu_hours.sum() * USD_GPU):.1f}x the whole GPU spend")

# ---- B. decomposition --------------------------------------------------------
tot = j.wait_sec.sum() / H
print(f"\nwait {tot:,.0f} h = pre-eligible {j.pre.sum()/H:,.0f} h ({j.pre.sum()/H/tot:.0%}) "
      f"+ queue {j.qw.sum()/H:,.0f} h ({j.qw.sum()/H/tot:.0%})")
print(f"  jobs held before eligible: {(j.pre > 0).sum():,}; of them array tasks {j[j.pre > 0].is_array_task.mean():.0%}")

# ---- C. distribution -----------------------------------------------------------
qs = j.qw.quantile([.5, .75, .9, .95, .99, .999])
print("\nqueue wait quantiles (job-weighted):", {k: f"{v/H:.2f}h" for k, v in qs.items()})
bins = [-1, 60, 600, H, 4 * H, 12 * H, 24 * H, 1e9]
labels = ["<1m", "1-10m", "10m-1h", "1-4h", "4-12h", "12-24h", ">24h"]
b = pd.cut(j.qw, bins, labels=labels)
t = j.groupby(b, observed=True).agg(jobs=("qw", "size"), hours=("qw", lambda s: s.sum() / H))
t["job_share"] = t.jobs / len(j); t["hour_share"] = t.hours / t.hours.sum()
print(t.to_string(float_format=lambda x: f"{x:,.3f}"))
top1 = j.qw >= j.qw.quantile(.99)
print(f"slowest 1% of jobs: {top1.sum()} jobs, {j.qw[top1].sum()/H:,.0f} h ({j.qw[top1].sum()/j.qw.sum():.0%} of queue hours)")

# ---- D. who waits ---------------------------------------------------------------
print("\nqueue hours by type / array:")
print(j.groupby(["job_type", "is_array_task"]).agg(jobs=("qw", "size"), med_s=("qw", "median"),
      p99_h=("qw", lambda s: s.quantile(.99) / H), hours=("qw", lambda s: s.sum() / H)).round(2).to_string())
w = pd.cut(j.gpu_count, [0, 1, 2, 8, 64], labels=["1", "2", "3-8", "9+"])
print("\nby width:")
print(j.groupby(w, observed=True).agg(jobs=("qw", "size"), med_s=("qw", "median"),
      p90_h=("qw", lambda s: s.quantile(.9) / H), p99_h=("qw", lambda s: s.quantile(.99) / H),
      hours=("qw", lambda s: s.sum() / H)).round(2).to_string())
# time limit asked for: the scheduler can only backfill jobs whose limit fits a gap
tl = j.timelimit.where(j.timelimit < 1e9)  # 4294967295 = unlimited
tlb = pd.cut(tl / 60, [0, 1, 4, 24, 72, 1e6], labels=["<=1h", "1-4h", "4-24h", "1-3d", ">3d"])
tlb = tlb.cat.add_categories("unlimited").fillna("unlimited")
print("\nby requested time limit:")
print(j.groupby(tlb, observed=True).agg(jobs=("qw", "size"), med_s=("qw", "median"),
      p90_h=("qw", lambda s: s.quantile(.9) / H), hours=("qw", lambda s: s.sum() / H),
      used=("walltime_sec", lambda s: (s / H).median())).round(2).to_string())

# ---- E. person-hours: merge each person's overlapping waits ------------------
def merged_hours(df, lo, hi):
    tot = 0.0
    per = {}
    for u, g in df.groupby("id_user"):
        iv = sorted(zip(g[lo].values, g[hi].values))
        s, e, acc = iv[0][0], iv[0][1], 0.0
        for a, c in iv[1:]:
            if a > e:
                acc += e - s; s, e = a, c
            else:
                e = max(e, c)
        acc += e - s
        per[u] = acc / H
        tot += acc / H
    return tot, pd.Series(per)

wq = j[j.qw > 0]
all_person, per_all = merged_hours(wq, "time_eligible", "time_start")
long_ = j[j.qw > TARGET].assign(lo=lambda d: d.time_eligible + TARGET)
past_person, per_past = merged_hours(long_, "lo", "time_start")
print(f"\nperson-hours waiting (merged per person): all queue time {all_person:,.0f} h; "
      f"only time past a 4 h target {past_person:,.0f} h")
print(f"  people with any wait past 4 h: {len(per_past)}; top 5 hold {per_past.nlargest(5).sum()/past_person:.0%}")
print(f"  interactive sessions, total queue time: {j[j.job_type=='LLSUB:INTERACTIVE'].qw.sum()/H:.1f} h;"
      f" p99 {j[j.job_type=='LLSUB:INTERACTIVE'].qw.quantile(.99):.0f}s")
days = (j.time_end.max() - j.time_start.min()) / 86400
print(f"  window {days:.0f} days = {days/7:.1f} weeks; past-target person-hours per affected person per week: "
      f"{past_person/len(per_past)/(days/7):.1f}")

# ---- F. contention: were GPUs full when people waited? -------------------------
grid = np.arange(j.time_start.min(), j.time_end.max(), 600.0)
def level(starts, ends, weight):
    so = np.argsort(starts); eo = np.argsort(ends)
    cs = np.concatenate([[0], np.cumsum(weight[so])]); ce = np.concatenate([[0], np.cumsum(weight[eo])])
    return cs[np.searchsorted(starts[so], grid, "right")] - ce[np.searchsorted(ends[eo], grid, "right")]
held = level(j.time_start.values, j.time_end.values, j.gpu_count.values.astype(float))
never = ((j.sm_util_avg == 0) & (j.sm_util_max == 0)).values
idle_held = level(j.time_start.values[never], j.time_end.values[never], j.gpu_count.values[never].astype(float))
lw = j.qw > H
pend = level(j.time_eligible.values[lw], j.time_start.values[lw], np.ones(lw.sum()))
pend_gpus = level(j.time_eligible.values[lw], j.time_start.values[lw], j.gpu_count.values[lw].astype(float))
CAP = 225 * 2
print(f"\nsample GPUs held: median {np.median(held):.0f}, p95 {np.percentile(held,95):.0f}, max {held.max():.0f} of {CAP}")
cont = pend > 0
print(f"share of time someone had waited >1 h and was still pending: {cont.mean():.0%}")
print(f"  GPUs held then: median {np.median(held[cont]):.0f} (vs {np.median(held[~cont]):.0f} otherwise)")
print(f"  of which held by jobs that never ran a kernel: median {np.median(idle_held[cont]):.0f}, "
      f"mean {idle_held[cont].mean():.1f}")
gh = idle_held[cont].sum() * 600 / H
print(f"  idle-held GPU-h while someone waited >1 h: {gh:,.0f} (${gh*USD_GPU:,.0f})")
cover = np.minimum(idle_held, pend_gpus)[cont]
print(f"  time when idle-held GPUs >= GPUs the long-waiters wanted: {(idle_held[cont] >= pend_gpus[cont]).mean():.0%}")
jq = j[lw]
at = np.searchsorted(grid, jq.time_eligible.values).clip(0, len(grid) - 1)
print(f"  at long-wait submissions, GPUs held: median {np.median(held[at]):.0f}; "
      f"corr(held at eligible, wait) = {np.corrcoef(held[at], jq.qw)[0,1]:.2f}")

# ---- G. weekly rhythm -------------------------------------------------------------
dt = pd.to_datetime(j.time_eligible + OFFSET, unit="s")
wd = j.groupby(dt.dt.day_name()).agg(subs=("qw", "size"), med_s=("qw", "median"),
                                     hours=("qw", lambda s: s.sum() / H), arr=("is_array_task", "mean"))
print("\nby weekday (epoch-anchored labels):")
print(wd.sort_values("subs", ascending=False).round(2).to_string())
peak = wd.subs.idxmax()
pk = j[dt.dt.day_name() == peak]
print(f"{peak}: array share {pk.is_array_task.mean():.0%} vs {j.is_array_task.mean():.0%} overall; "
      f"top owner holds {pk.id_user.value_counts(normalize=True).iloc[0]:.0%} of its submissions")

# ---- H. the SLO weeks ------------------------------------------------------------
wk = pd.to_datetime(j.time_start + OFFSET, unit="s").dt.to_period("W-TUE").dt.start_time
s = j.groupby([j.partition, wk]).agg(n=("qw", "size"), p95=("wait_sec", lambda x: x.quantile(.95) / H),
                                      med=("wait_sec", lambda x: x.median() / H),
                                      past=("wait_sec", lambda x: (x - TARGET).clip(lower=0).sum() / H),
                                      users=("id_user", "nunique"))
br = s[(s.n >= 100) & (s.p95 > 4)]
print("\nweeks breaching p95 > 4 h (wait_sec, weeks starting Wed):")
print(br.round(2).to_string())
f = pd.json_normalize(json.load(open("data/synthetic/findings.json")))
slo = f[f.detectorId == "rules::queue-wait-p95-slo"]
print("finding weeks:", sorted(slo["metadata.week_start"]))

# ---- I. money, several ways ---------------------------------------------------------
print("\nmonetised at $95/engineer-hour:")
for name, h in (("API: every job's full wait", row["total_wait_hours"]),
                ("queue time only, every job", j.qw.sum() / H),
                ("queue time, merged per person", all_person),
                ("past a 4 h target, merged per person", past_person),
                ("interactive sessions only", j[j.job_type == "LLSUB:INTERACTIVE"].qw.sum() / H)):
    print(f"  {name:40s} {h:>10,.0f} h  ${h*USD_ENG:>12,.0f}")

# ---- J. risk of a 20% cut ----------------------------------------------------------
print("\nif capacity fell 20% (sample occupancy vs 360 of 450 GPUs):")
print(f"  share of time sample holds >360 GPUs: {(held > 360).mean():.1%}; >300: {(held > 300).mean():.1%}")
print(f"  share of time held minus idle-held > 360: {((held - idle_held) > 360).mean():.1%}")

# ---- K. the two queue findings, reconciled ------------------------------------------
top = j[j.id_user == 41415979807]
tdt = pd.to_datetime(top.time_eligible + OFFSET, unit="s")
print(f"\nweekly-peak check: owner u-41415979807 submitted {(tdt.dt.date == pd.Timestamp('2026-04-01').date()).sum():,} jobs on 2026-04-01;"
      f" median runtime {top.walltime_sec.median():.0f}s; {top.qw.sum()/j.qw.sum():.0%} of all queue hours")
st = f[f.detectorId == "rules::queue-starvation"]
users = st["metadata.owner"].str[2:].astype("int64")
lw = j[j.id_user.isin(users) & (j.wait_sec > 6 * H)]
print(f"starvation findings: {st['metadata.queue_hours'].sum():,.0f} h = pre-eligible {lw.pre.sum()/H:,.0f} h"
      f" + queue {lw.qw.sum()/H:,.0f} h; u-59477077536: pre {lw[lw.id_user == 59477077536].pre.sum()/H:,.0f} h,"
      f" queue {lw[lw.id_user == 59477077536].qw.sum()/H:,.0f} h")
