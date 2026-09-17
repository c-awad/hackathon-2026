"""Case 9b -- simulate the scheduler WITH per-user caps, then optimize it.

Case 9 replayed every job at 450 GPUs and produced waits ~18x below the observed
ones. The missing constraint was not load: it was the per-user concurrency cap.
This script adds the cap, checks the model against the real waits, and only then
measures what the optimizations are worth.

The simulator itself lives in analysis/sched_sim.py, which the dashboard imports
too -- so the tile and this write-up cannot drift apart.

Every startable job in the dataset is included. The dataset is MIT's published
*sample* of the cluster's jobs; the unsampled work is not in the files and cannot
be added, so the cap model is validated against the observed wait distribution and
reported with its error.
"""
import numpy as np
import pandas as pd

from sched_sim import H, Sim

USD_ENG = 95.0

sim = Sim(pd.read_parquet("data/prepped/jobs.parquet"))
print(f"jobs in simulation: {len(sim.j):,} of {sim.n_total:,} in the dataset "
      f"({sim.n_total - len(sim.j)} never started, so they have no observed wait)")
print(f"per-user caps: {len(sim.caps_user)} users, {sim.snapped} snapped onto the 16/32/64 "
      f"ladder; median cap {np.median(list(sim.caps_user.values())):.0f} GPUs\n")


def show(name, wait):
    r = sim.summarize(name, wait)
    print(f"{name:34s} total {r['total_h']:9,.0f} h | p50 {r['p50_s']:7,.0f}s | "
          f"p95 {r['p95_h']:6.2f} h | p99 {r['p99_h']:7.2f} h | >4h {r['over_4h']:5d} | "
          f"person-h {r['person_h']:8,.0f}")
    return r


rows = [show("OBSERVED (real scheduler)", sim.observed)]
w_caps = sim.run(caps=True)
rows.append(show("MODEL: FCFS + backfill + caps", w_caps))
rows.append(show("MODEL: no caps (case 9)", sim.run(caps=False)))

print("\n-- does the cap model match reality? --")
for q in (50, 75, 90, 95, 99):
    print(f"  p{q:<3} observed {np.percentile(sim.observed, q)/H:8.2f} h   "
          f"model {np.percentile(w_caps, q)/H:8.2f} h")
print(f"  total     observed {sim.observed.sum()/H:8,.0f} h   model {w_caps.sum()/H:8,.0f} h "
      f"({w_caps.sum()/sim.observed.sum():.0%} of observed)")
print(f"  person-h  observed {sim.person_hours(sim.observed):8,.0f} h   "
      f"model {sim.person_hours(w_caps):8,.0f} h")

print("\n-- now vs optimized (all figures from the cap model) --")
variants = {
    "NOW: caps as they are": {},
    "OPT 1: 1h idle timeout": dict(idle_kill_h=1.0),
    "OPT 2: elastic cap under 70%": dict(elastic_below=0.70),
    "OPT 3: both": dict(idle_kill_h=1.0, elastic_below=0.70),
    "OPT 4: both + SJF order": dict(idle_kill_h=1.0, elastic_below=0.70, sjf=True),
    "REF: double every cap": dict(cap_mult=2.0),
    "REF: no caps at all": dict(caps=False),
}
res = {name: show(name, sim.run(**kw)) for name, kw in variants.items()}
rows += list(res.values())
base = res["NOW: caps as they are"]
print("\nagainst 'caps as they are':")
for name, r in res.items():
    if name.startswith("NOW"):
        continue
    print(f"  {name:32s} person-hours {r['person_h']-base['person_h']:+9,.0f} h "
          f"({r['person_h']/base['person_h']-1:+6.1%}) | >4h jobs {r['over_4h']-base['over_4h']:+6d} | "
          f"${(r['person_h']-base['person_h'])*USD_ENG:+11,.0f}")
pd.DataFrame(rows).to_csv("analysis/out_case9b_caps.csv", index=False)

print("\n-- elastic threshold sweep (with the 1h idle timeout on) --")
sweep = []
for thr in (0.50, 0.60, 0.70, 0.80, 0.90):
    r = sim.summarize(f"elastic below {thr:.0%}", sim.run(idle_kill_h=1.0, elastic_below=thr))
    r["threshold"] = thr
    sweep.append(r)
    print(f"  below {thr:.0%} allocated: person-hours {r['person_h']:8,.0f} "
          f"({r['person_h']/base['person_h']-1:+6.1%}) | >4h {r['over_4h']:5d} | p99 {r['p99_h']:5.2f} h")
pd.DataFrame(sweep).to_csv("analysis/out_case9b_sweep.csv", index=False)
print("\nwrote analysis/out_case9b_caps.csv and analysis/out_case9b_sweep.csv")
