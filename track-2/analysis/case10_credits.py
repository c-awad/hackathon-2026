"""Case 10 -- forecast each researcher's quota, and let them lend it out.

Case 9b's "elastic quota" lifts the cap whenever the cluster is quiet. That is
reactive: it hands out slots with no idea who is about to arrive, and without
preemption a long job started in a quiet hour still holds the cards when everyone
comes back. This script builds and measures the two alternatives:

  PREDICTED CAP   size each researcher's quota from their OWN past demand, using
                  only data available before the week it applies to.

  CREDITS POOL    a researcher who has been away lends their unused quota to the
                  pool for a bounded window; a waiting job may borrow from it only
                  if its requested time limit fits inside that window, so the loan
                  is returned before the lender plausibly needs it back.

Everything is causal: no policy sees a job before it is eligible, and the forecast
never reads the week it is predicting. The failure mode we care about is the lender
coming back to find their quota on loan -- that is measured, not assumed.
"""
import heapq

import numpy as np
import pandas as pd

from sched_sim import CAP_TOTAL, H, Sim

WEEK = 7 * 86400
UNLIMITED = 4294967295          # Slurm's "no time limit"
AWAY_H = 4.0                    # idle this long with nothing queued -> you are away
LOAN_H = 8.0                    # a loan lasts this long, so only short jobs may borrow
USD_ENG = 95.0
TARGET = 4 * H
WINDOW = 600

import os
jobs = pd.read_parquet("data/prepped/jobs.parquet")
SHORT_WEEKS = int(os.environ.get("SHORT_WEEKS", "0"))
if SHORT_WEEKS:
    cut = jobs.time_eligible.min() + SHORT_WEEKS * 7 * 86400
    jobs = jobs[jobs.time_eligible < cut]
    print(f"SHORT RUN: first {SHORT_WEEKS} weeks only", flush=True)
sim = Sim(jobs)
j = sim.j
ELIG, GPUS, DUR, UI = sim.ELIG, sim.GPUS, sim.DUR0, sim.UI
NU = len(sim.uidx)
NEVER = sim.NEVER
LIMIT_S = j.timelimit.where(j.timelimit < UNLIMITED).mul(60).to_numpy(dtype=float)  # NaN = unlimited
HAS_LIMIT = ~np.isnan(LIMIT_S)
print(f"{len(j):,} jobs, {NU} researchers. Jobs with an honest time limit: "
      f"{HAS_LIMIT.mean():.0%} (the rest request none, so they can never borrow)", flush=True)

# ------------------------------------------------ predicted runtime, per job
# Requested limits over-ask by ~2,000x (median limit 24 h, median runtime ~1 min),
# so they cannot gate a loan. A job's runtime IS predictable from its owner's own
# history: p90 of the durations of their jobs that had finished before this one
# became eligible. Strictly causal.
import bisect
PRED_S = np.full(len(j), np.nan)
for _u, _g in j.groupby("id_user"):
    _done, _fly = [], []
    for _idx, _el, _d in zip(_g.index, _g.elig.values, _g.dur.values):
        while _fly and _fly[0][0] <= _el:
            bisect.insort(_done, heapq.heappop(_fly)[1])
        if len(_done) >= 5:
            PRED_S[_idx] = _done[min(int(0.9 * len(_done)), len(_done) - 1)]
        heapq.heappush(_fly, (_el + _d, _d))
MEAN_JOB_H = float(DUR.mean() / H)
print(f"mean job length {MEAN_JOB_H:.2f} h (median {np.median(DUR)/H:.2f} h); "
      f"{np.isfinite(PRED_S).mean():.0%} of jobs have a usable runtime prediction", flush=True)

# ---------------------------------------------------------------- the forecast
# Offered load: what a researcher ASKED for, independent of when it actually ran,
# so the forecast does not depend on the policy being simulated.
t0, t1 = ELIG.min(), (ELIG + DUR).max()
weeks = np.arange(t0, t1 + WEEK, WEEK)
WK = np.clip(((ELIG - t0) // WEEK).astype(int), 0, len(weeks) - 1)

def user_load_curve(u):
    """Step function of a researcher's in-flight GPU demand: (times, level).

    Built from eligibility and runtime only, so it does not depend on the policy
    being simulated -- the forecast reads demand, not what the scheduler granted.
    """
    m = UI == u
    if not m.any():
        return np.array([t0]), np.array([0.0])
    starts, ends, gp = ELIG[m], (ELIG + DUR)[m], GPUS[m].astype(float)
    t = np.concatenate([starts, ends])
    dv = np.concatenate([gp, -gp])
    o = np.argsort(t, kind="stable")
    return t[o], np.cumsum(dv[o])


def peak_in(times, level, lo, hi):
    """Peak of the step function over [lo, hi): the most GPUs this researcher had
    in flight at once. (An earlier version took a time-weighted percentile, which
    is dominated by idle hours and collapsed every quota to 1 GPU.)"""
    if not len(times):
        return 0.0
    i0 = max(np.searchsorted(times, lo, "right") - 1, 0)
    i1 = np.searchsorted(times, hi, "left")
    seg = level[i0:i1]
    return float(seg.max()) if len(seg) else 0.0


QUOTA_MAX = 64.0                # the top rung of today's ladder; a forecast never exceeds it
QUOTA_MIN = 2.0                 # one node

print("forecasting each researcher's quota from their previous two weeks...", flush=True)
FORECAST = np.zeros((NU, len(weeks)))
for u in range(NU):
    times, level = user_load_curve(u)
    for w in range(len(weeks)):
        p = peak_in(times, level, weeks[w] - 2 * WEEK, weeks[w])
        # no demand in the last two weeks -> the cluster default of 16
        FORECAST[u, w] = float(np.clip(np.ceil(p), QUOTA_MIN, QUOTA_MAX)) if p > 0 else 16.0
CAP_NOW = sim.USER_CAP.copy()
print(f"  today's median quota {np.median(CAP_NOW):.0f} GPUs; "
      f"forecast median {np.median(FORECAST[FORECAST > 0]):.0f}")
tight = (FORECAST[:, 1:] < CAP_NOW[:, None]).mean()
print(f"  the forecast is TIGHTER than today's quota in {tight:.0%} of researcher-weeks "
      f"(it hands capacity back rather than only giving it away)")


def simulate(policy="now", elastic_below=None, pool=False, idle_kill_h=None,
             loan_h=LOAN_H, away_h=AWAY_H, gate="limit"):
    """policy: 'now' (fixed quotas) | 'predict' (forecast quotas) | 'none'.

    The credits pool does NOT transfer quota. A researcher who is away (nothing
    running, nothing queued, for `away_h` hours) makes their quota available to the
    pool; their own quota is never reduced, so they are never blocked by their own
    generosity. A waiting job may run over its owner's quota only if its requested
    time limit fits inside `loan_h`, so every loan is back within the window. The
    cost of lending therefore lands on the CLUSTER (borrowed jobs occupy cards),
    and the harm we measure is exactly that: researcher-hours spent queued, under
    their own quota, because the cluster was full while borrowed jobs were running.
    """
    dur = DUR.copy()
    if idle_kill_h is not None:
        dur[NEVER] = np.minimum(dur[NEVER], idle_kill_h * H)

    wait = np.full(len(j), np.nan)
    free = CAP_TOTAL
    used = np.zeros(NU)
    borrowed = np.zeros(NU)          # slots each researcher is running over quota
    last_active = np.full(NU, -1e18)
    pending_count = np.zeros(NU, dtype=int)
    running, pend = [], []
    nxt = seq = 0
    now = ELIG[0]
    n = len(j)
    borrowed_gpu_h = 0.0
    harm_h = 0.0
    overrun_gpu_h = 0.0

    def caps_at(t):
        if policy == "none":
            return np.full(NU, np.inf)
        if policy == "predict":
            return FORECAST[:, min(int((t - t0) // WEEK), FORECAST.shape[1] - 1)]
        return CAP_NOW

    while nxt < n or pend or running:
        while nxt < n and ELIG[nxt] <= now:
            heapq.heappush(pend, (ELIG[nxt], seq, nxt))
            pending_count[UI[nxt]] += 1
            last_active[UI[nxt]] = now
            seq += 1
            nxt += 1
        caps = caps_at(now)
        if pool:
            away = (last_active < now - away_h * H) & (used == 0) & (pending_count == 0)
            pool_cap = float(caps[away & np.isfinite(caps)].sum())
        else:
            pool_cap = 0.0

        progress = True
        while progress and pend:
            progress = False
            held = [heapq.heappop(pend) for _ in range(min(WINDOW, len(pend)))]
            quiet = elastic_below is not None and (CAP_TOTAL - free) / CAP_TOTAL < elastic_below
            for pos, (_, _, i) in enumerate(held):
                g, u = GPUS[i], UI[i]
                if g > free:
                    continue
                cap = np.inf if quiet else caps[u]
                over = max(0.0, used[u] + g - cap)          # slots beyond my own quota
                if over > 0:
                    fits = (PRED_S[i] <= loan_h * H) if gate == "history" else \
                           (HAS_LIMIT[i] and LIMIT_S[i] <= loan_h * H)
                    ok = (pool and fits
                          and borrowed.sum() + over <= pool_cap     # the pool can cover it
                          and borrowed[u] + over <= cap)            # at most double my quota
                    if not ok:
                        continue
                held.pop(pos)
                free -= g
                used[u] += g
                if over > 0:
                    borrowed[u] += over
                    borrowed_gpu_h += over * dur[i] / H
                    if dur[i] > loan_h * H:          # the prediction was wrong
                        overrun_gpu_h += over * (dur[i] - loan_h * H) / H
                wait[i] = now - ELIG[i]
                pending_count[u] -= 1
                heapq.heappush(running, (now + max(dur[i], 1.0), g, u, over))
                progress = True
                break
            for item in held:
                heapq.heappush(pend, item)

        cands = [running[0][0]] if running else []
        if nxt < n:
            cands.append(ELIG[nxt])
        if not cands:
            break
        nxt_t = min(cands)
        # harm: someone is queued UNDER their own quota, the cluster is full, and
        # borrowed jobs are part of what is filling it
        if pool and borrowed.sum() > 0 and free < 1:
            victims = int(((pending_count > 0) & (used < caps)).sum())
            harm_h += victims * (nxt_t - now) / H
        now = nxt_t
        while running and running[0][0] <= now:
            _, g, u, ov = heapq.heappop(running)
            free += g
            used[u] -= g
            last_active[u] = now
            if ov:
                borrowed[u] -= ov
    return (np.nan_to_num(wait, nan=0.0),
            {"borrowed_gpu_h": borrowed_gpu_h, "lender_blocked_h": harm_h,
             "overrun_gpu_h": overrun_gpu_h})


def report(name, wait, extra=None, base=None):
    ph = sim.person_hours(wait)
    r = {"policy": name, "person_h": round(ph, 1), "total_h": round(wait.sum() / H, 1),
         "over_4h": int((wait > TARGET).sum()),
         "p95_h": round(float(np.percentile(wait, 95)) / H, 2),
         "p99_h": round(float(np.percentile(wait, 99)) / H, 2), "usd": round(ph * USD_ENG)}
    if extra:
        r.update({k: round(v, 1) for k, v in extra.items()})
    line = (f"{name:32s} person-h {r['person_h']:8,.1f} | >4h {r['over_4h']:5d} | "
            f"p95 {r['p95_h']:5.2f} | p99 {r['p99_h']:6.2f}")
    if base is not None:
        line += f" | vs now {ph/base-1:+7.1%}"
    if extra:
        line += (f" | borrowed {extra['borrowed_gpu_h']:8,.0f} GPU-h | "
                 f"harm {extra['lender_blocked_h']:7,.1f} h")
    print(line)
    return r


print("\n-- policies --", flush=True)
rows = []
w_now, _ = simulate("now")
base = sim.person_hours(w_now)
rows.append(report("NOW: fixed quotas", w_now))
w_el, _ = simulate("now", elastic_below=0.70)
rows.append(report("Elastic quota under 70%", w_el, base=base))
w_pr, _ = simulate("predict")
rows.append(report("Predicted quota (2-week history)", w_pr, base=base))
w_lim, x_lim = simulate("now", pool=True, loan_h=MEAN_JOB_H, gate="limit")
rows.append(report("Pool, gated on REQUESTED limit", w_lim, x_lim, base))
w_pool, x_pool = simulate("now", pool=True, loan_h=MEAN_JOB_H, gate="history")
rows.append(report("Pool, gated on PREDICTED runtime", w_pool, x_pool, base))
w_pk, x_pk = simulate("now", pool=True, loan_h=MEAN_JOB_H, gate="history", idle_kill_h=1.0)
rows.append(report("Pool (predicted) + idle timeout", w_pk, x_pk, base))
w_none, _ = simulate("none")
rows.append(report("Reference: no quotas", w_none, base=base))

print("\n-- who wins and who loses (person-hours per researcher) --")
d = pd.DataFrame({"u": sim.UID, "now": w_now, "elastic": w_el, "predict": w_pr, "pool": w_pool})
per = d.groupby("u").sum() / H
for col in ("elastic", "predict", "pool"):
    delta = per[col] - per["now"]
    print(f"  {col:9s} better {int((delta < -0.01).sum()):4d} | worse {int((delta > 0.01).sum()):4d} | "
          f"worst single researcher {delta.max():+8.1f} h | net {delta.sum():+10.1f} h")

print("\n-- the pool's risks, measured --")
print(f"  borrowed {x_pool['borrowed_gpu_h']:,.0f} GPU-h; of it {x_pool['overrun_gpu_h']:,.0f} GPU-h "
      f"({x_pool['overrun_gpu_h']/max(x_pool['borrowed_gpu_h'],1):.1%}) ran past the loan window because "
      f"the runtime prediction was wrong")
print(f"  researchers queued under their own quota while the cluster was full and borrowed jobs "
      f"were running: {x_pool['lender_blocked_h']:,.1f} researcher-hours")

print("\n-- loan window sweep (pool on today's quotas, gated on predicted runtime) --")
sw = []
for loan in (1.0, 2.0, MEAN_JOB_H, 12.0, 24.0):
    w, x = simulate("now", pool=True, loan_h=loan, gate="history")
    ph = sim.person_hours(w)
    sw.append({"loan_h": round(loan, 2), "person_h": round(ph, 1),
               "borrowed_gpu_h": round(x["borrowed_gpu_h"]), "overrun_gpu_h": round(x["overrun_gpu_h"]),
               "harm_h": round(x["lender_blocked_h"], 1)})
    print(f"  window {loan:5.2f}h: person-h {ph:8,.1f} ({ph/base-1:+6.1%}) | borrowed "
          f"{x['borrowed_gpu_h']:8,.0f} GPU-h | overran {x['overrun_gpu_h']:7,.0f} | harm {x['lender_blocked_h']:6.1f} h")

pd.DataFrame(rows).to_csv("analysis/out_case10_policies.csv", index=False)
pd.DataFrame(sw).to_csv("analysis/out_case10_loan_sweep.csv", index=False)
print("\nwrote analysis/out_case10_policies.csv and analysis/out_case10_loan_sweep.csv")
