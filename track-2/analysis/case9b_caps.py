"""Case 9b -- simulate the scheduler WITH per-user caps, then optimize it.

Case 9 replayed every job at 450 GPUs and produced waits ~18x below the observed
ones. The missing constraint was not load: it was the per-user concurrency cap.
This script adds the cap, checks the model against the real waits, and only then
measures what the optimizations are worth.

Every job in the dataset is included (74,838 with a start time, plus the 11 that
never started are excluded because they have no observed wait to compare against).
The dataset itself is MIT's published *sample* of the cluster's jobs; the rest of
the machine's work is not in the files and cannot be added. Instead of pretending
otherwise, the cap model is validated against the observed wait distribution and
reported with its error.
"""
import heapq

import numpy as np
import pandas as pd

CAP_TOTAL = 225 * 2
H = 3600.0
USD_ENG = 95.0
TARGET = 4 * H
WINDOW = 600

j = pd.read_parquet("data/prepped/jobs.parquet")
j = j[j.time_start.notna()].copy()
j["dur"] = j.walltime_sec.fillna(0).clip(lower=0)
j["elig"] = j.time_eligible
j["qw_real"] = (j.time_start - j.time_eligible).clip(lower=0)
j["never_ran"] = ((j.sm_util_avg == 0) & (j.sm_util_max == 0)).values
j = j.sort_values("elig").reset_index(drop=True)
print(f"jobs in simulation: {len(j):,} of {74849:,} in the dataset "
      f"({74849 - len(j)} never started, so they have no observed wait)")


def observed_peak_concurrency(df):
    """Each user's peak simultaneous GPUs, swept from their real start/end times."""
    out = {}
    for u, g in df.groupby("id_user"):
        ev = np.concatenate([
            np.stack([g.time_start.to_numpy(), g.gpu_count.to_numpy()], 1),
            np.stack([g.time_end.to_numpy(), -g.gpu_count.to_numpy()], 1)])
        ev = ev[np.argsort(ev[:, 0], kind="stable")]
        out[u] = int(np.cumsum(ev[:, 1]).max())
    return pd.Series(out)


peak = observed_peak_concurrency(j)
# The quota ladder visible in the data: heavy users pile up at 16/17, 32, 64-66.
LADDER = np.array([16, 32, 64])


def snap(v):
    """Round a user's observed peak onto the nearest quota rung, within 10%."""
    d = np.abs(LADDER - v) / LADDER
    k = int(np.argmin(d))
    return int(LADDER[k]) if d[k] <= 0.10 else int(v)


caps_user = {u: snap(v) for u, v in peak.items()}
snapped = sum(1 for u, v in peak.items() if caps_user[u] != v)
print(f"per-user caps: {len(caps_user)} users, {snapped} snapped onto the 16/32/64 ladder; "
      f"median cap {np.median(list(caps_user.values())):.0f} GPUs")

U = j.id_user.map(caps_user).to_numpy(dtype=float)
ELIG = j.elig.to_numpy(dtype=float)
GPUS = j.gpu_count.to_numpy(dtype=int)
DUR0 = j.dur.to_numpy(dtype=float)
NEVER = j.never_ran.to_numpy()
UID = j.id_user.to_numpy()
uidx = {u: k for k, u in enumerate(sorted(set(UID)))}
UI = np.array([uidx[u] for u in UID])
NU = len(uidx)
USER_CAP = np.zeros(NU)
for u, k in uidx.items():
    USER_CAP[k] = caps_user[u]


def simulate(policy="caps", idle_kill_h=None, elastic_below=None, cap_mult=1.0, sjf=False):
    """Replay every job. `elastic_below`: let a user exceed their cap while the
    cluster is below this allocated fraction (the jobs are then preemptible in
    principle; here they simply run)."""
    dur = DUR0.copy()
    if idle_kill_h is not None:
        dur[NEVER] = np.minimum(dur[NEVER], idle_kill_h * H)
    caps = USER_CAP * cap_mult if policy == "caps" else np.full(NU, np.inf)
    key = dur if sjf else ELIG

    wait = np.full(len(j), np.nan)
    free = CAP_TOTAL
    user_used = np.zeros(NU)
    running = []      # (end, gpus, user_index)
    pending = []      # (key, seq, idx)
    nxt = seq = 0
    now = ELIG[0]
    n = len(j)
    while nxt < n or pending or running:
        while nxt < n and ELIG[nxt] <= now:
            heapq.heappush(pending, (key[nxt], seq, nxt))
            seq += 1
            nxt += 1
        # try to start jobs: cluster capacity AND the owner's quota must allow it
        progress = True
        while progress and pending:
            progress = False
            held = [heapq.heappop(pending) for _ in range(min(WINDOW, len(pending)))]
            for pos, (_, _, i) in enumerate(held):
                g, ui = GPUS[i], UI[i]
                cap = caps[ui]
                if elastic_below is not None and (CAP_TOTAL - free) / CAP_TOTAL < elastic_below:
                    cap = np.inf
                if g <= free and user_used[ui] + g <= cap:
                    held.pop(pos)
                    free -= g
                    user_used[ui] += g
                    wait[i] = now - ELIG[i]
                    heapq.heappush(running, (now + max(dur[i], 1.0), g, ui))
                    progress = True
                    break
            for item in held:
                heapq.heappush(pending, item)
        cands = [running[0][0]] if running else []
        if nxt < n:
            cands.append(ELIG[nxt])
        if not cands:
            break
        now = min(cands)
        while running and running[0][0] <= now:
            _, g, ui = heapq.heappop(running)
            free += g
            user_used[ui] -= g
    return np.nan_to_num(wait, nan=0.0)


def person_hours(wait):
    d = pd.DataFrame({"u": UID, "lo": ELIG, "hi": ELIG + wait})
    d = d[d.hi > d.lo]
    total = 0.0
    for _, g in d.groupby("u"):
        iv = sorted(zip(g.lo.to_numpy(), g.hi.to_numpy()))
        s, e, acc = iv[0][0], iv[0][1], 0.0
        for a, b in iv[1:]:
            if a > e:
                acc += e - s
                s, e = a, b
            else:
                e = max(e, b)
        total += (acc + e - s) / H
    return total


def row(name, wait):
    past = np.maximum(wait - TARGET, 0).sum() / H
    ph = person_hours(wait)
    r = {"policy": name, "total_h": wait.sum() / H, "p50_s": np.percentile(wait, 50),
         "p95_h": np.percentile(wait, 95) / H, "p99_h": np.percentile(wait, 99) / H,
         "over_4h": int((wait > TARGET).sum()), "past_target_h": past, "person_h": ph,
         "usd": ph * USD_ENG}
    print(f"{name:34s} total {r['total_h']:9,.0f} h | p50 {r['p50_s']:7,.0f}s | p95 {r['p95_h']:6.2f} h | "
          f"p99 {r['p99_h']:7.2f} h | >4h {r['over_4h']:5d} | person-h {ph:8,.0f}")
    return r


print()
obs = j.qw_real.to_numpy(dtype=float)
rows = [row("OBSERVED (real scheduler)", obs)]
w_caps = simulate(policy="caps")
rows.append(row("MODEL: FCFS + backfill + caps", w_caps))
rows.append(row("MODEL: no caps (case 9)", simulate(policy="none")))

print("\n-- does the cap model match reality? --")
for q in (50, 75, 90, 95, 99):
    print(f"  p{q:<3} observed {np.percentile(obs, q)/H:8.2f} h   model {np.percentile(w_caps, q)/H:8.2f} h")
print(f"  total     observed {obs.sum()/H:8,.0f} h   model {w_caps.sum()/H:8,.0f} h "
      f"({w_caps.sum()/obs.sum():.0%} of observed)")
print(f"  person-h  observed {person_hours(obs):8,.0f} h   model {person_hours(w_caps):8,.0f} h")

print("\n-- now vs optimized (all figures from the cap model) --")
variants = {
    "NOW: caps as they are": dict(policy="caps"),
    "OPT 1: 1h idle timeout": dict(policy="caps", idle_kill_h=1.0),
    "OPT 2: elastic cap under 70%": dict(policy="caps", elastic_below=0.70),
    "OPT 3: both": dict(policy="caps", idle_kill_h=1.0, elastic_below=0.70),
    "OPT 4: both + SJF order": dict(policy="caps", idle_kill_h=1.0, elastic_below=0.70, sjf=True),
    "REF: double every cap": dict(policy="caps", cap_mult=2.0),
    "REF: no caps at all": dict(policy="none"),
}
res = {}
for name, kw in variants.items():
    res[name] = row(name, simulate(**kw))
    rows.append(res[name])

base = res["NOW: caps as they are"]
print("\nagainst 'caps as they are':")
for name, r in res.items():
    if name.startswith("NOW"):
        continue
    print(f"  {name:32s} person-hours {r['person_h']-base['person_h']:+9,.0f} h "
          f"({r['person_h']/base['person_h']-1:+6.1%}) | >4h jobs {r['over_4h']-base['over_4h']:+6d} | "
          f"${r['usd']-base['usd']:+11,.0f}")

pd.DataFrame(rows).round(2).to_csv("analysis/out_case9b_caps.csv", index=False)
print("\nwrote analysis/out_case9b_caps.csv")

# -- how sensitive is OPT 2 to where the elastic threshold sits? --------------
print("\n-- elastic threshold sweep (with the 1h idle timeout on) --")
sweep = []
for thr in (0.50, 0.60, 0.70, 0.80, 0.90):
    w = simulate(policy="caps", idle_kill_h=1.0, elastic_below=thr)
    ph = person_hours(w)
    sweep.append({"threshold": thr, "person_h": ph, "over_4h": int((w > TARGET).sum()),
                  "p99_h": np.percentile(w, 99) / H})
    print(f"  let users exceed their cap below {thr:.0%} allocated: person-hours {ph:8,.0f} "
          f"({ph/base['person_h']-1:+6.1%}) | >4h {int((w > TARGET).sum()):5d} | "
          f"p99 {np.percentile(w, 99)/H:5.2f} h")
pd.DataFrame(sweep).round(2).to_csv("analysis/out_case9b_sweep.csv", index=False)
print("wrote analysis/out_case9b_sweep.csv")
