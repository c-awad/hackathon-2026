"""Precompute the credits-pool grid for the dashboard's interactive control.

Each pool simulation is a full replay of all startable jobs (~45 s), too slow to
run when the dashboard container starts, so the grid is computed once here and
written to analysis/out_case10_grid.json -- policy-level aggregates only, no job
data. Runs the simulations in parallel.

    PYTHONPATH=analysis python3 analysis/case10_grid.py
"""
import json
import multiprocessing as mp
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

# Load case 10's definitions (forecast, simulate) without running its policy block.
_src = open(os.path.join(os.path.dirname(__file__), "case10_credits.py")).read()
_src = _src.split('print("\\n-- policies --"')[0]
NS = {"__name__": "case10_defs"}
exec(compile(_src, "case10_credits.py", "exec"), NS)
simulate, sim, H, MEAN_JOB_H = NS["simulate"], NS["sim"], NS["H"], NS["MEAN_JOB_H"]
TARGET = 4 * H
WINDOWS = [1.0, 2.0, round(MEAN_JOB_H, 2), 12.0, 24.0]


def run(cfg):
    kind, window, gate, kill = cfg
    if kind == "base":
        w, x = simulate("now", idle_kill_h=1.0 if kill else None)
    else:
        w, x = simulate("now", pool=True, loan_h=window, gate=gate,
                        idle_kill_h=1.0 if kill else None)
    return {"kind": kind, "window_h": window, "gate": gate, "idle_kill": kill,
            "person_h": round(sim.person_hours(w), 1), "over_4h": int((w > TARGET).sum()),
            "p95_h": round(float(np.percentile(w, 95)) / H, 2),
            "p99_h": round(float(np.percentile(w, 99)) / H, 2),
            "borrowed_gpu_h": round(x.get("borrowed_gpu_h", 0.0)),
            "overrun_gpu_h": round(x.get("overrun_gpu_h", 0.0)),
            "harm_h": round(x.get("lender_blocked_h", 0.0), 1)}


if __name__ == "__main__":
    cfgs = [("base", None, None, False), ("base", None, None, True)]
    cfgs += [("pool", w, "history", k) for w in WINDOWS for k in (False, True)]
    cfgs += [("pool", w, "limit", False) for w in WINDOWS]
    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 4),
                             mp_context=mp.get_context("fork")) as ex:
        rows = list(ex.map(run, cfgs))
    out = {"mean_job_h": round(MEAN_JOB_H, 2), "windows": WINDOWS, "jobs": int(len(sim.j)),
           "away_h": NS["AWAY_H"], "rows": rows}
    json.dump(out, open("analysis/out_case10_grid.json", "w"), indent=1)
    for r in rows:
        print(r)
    print("wrote analysis/out_case10_grid.json")
