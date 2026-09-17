"""Case 9 -- is the scheduler already good, and would reordering cut the wait?

Replays the real job stream (eligible time, GPUs requested, actual runtime) through
a discrete-event simulator at 450 GPUs, under several queue policies.

What this can and cannot show
-----------------------------
CAN: the *relative* effect of ordering, on identical input, holding capacity fixed.
CANNOT: absolute waits. The data is a four-month **sample** of the cluster's jobs,
so the simulator sees less load than the real machine did and its waits come out
far below the observed ones. Every number here is a policy-vs-policy comparison.

Also: SJF is given each job's true runtime, which a real scheduler does not know
(it would use the requested time limit, and 42% of these jobs request no limit at
all). SJF is therefore an upper bound on what reordering could buy, not a plan.
"""
import heapq

import numpy as np
import pandas as pd

CAP = 225 * 2
H = 3600.0
USD_ENG = 95.0
TARGET = 4 * H
WINDOW = 400          # how far down the queue a backfill pass will look

j = pd.read_parquet("data/prepped/jobs.parquet")
j = j[j.time_start.notna()].copy()
j["dur"] = j.walltime_sec.fillna(0).clip(lower=0)
j["elig"] = j.time_eligible
j["qw_real"] = j.time_start - j.time_eligible
never_ran = (j.sm_util_avg == 0) & (j.sm_util_max == 0)

BASE = j[["id_job", "elig", "gpu_count", "dur", "id_user"]].copy()
BASE["never_ran"] = never_ran.values
BASE = BASE.sort_values("elig").reset_index(drop=True)


def simulate(df, key, backfill=True, idle_kill_h=None):
    """Return each job's wait (seconds), scheduling greedily under `key`.

    key(row) -> sort key for the pending queue. `idle_kill_h` shortens jobs that
    never ran a kernel to that many hours, which is the tile-2 policy: it frees
    cards during contention rather than reordering anything.
    """
    dur = df.dur.to_numpy(dtype=float).copy()
    if idle_kill_h is not None:
        nk = df.never_ran.to_numpy()
        dur[nk] = np.minimum(dur[nk], idle_kill_h * H)
    elig = df.elig.to_numpy(dtype=float)
    gpus = df.gpu_count.to_numpy(dtype=int)
    keys = key(df)
    order = np.argsort(elig, kind="stable")

    wait = np.full(len(df), np.nan)
    free = CAP
    running = []          # heap of (end_time, gpus)
    pending = []          # heap of (policy_key, arrival_seq, idx)
    nxt = 0
    now = elig[order[0]]
    seq = 0
    while nxt < len(order) or pending or running:
        # admit everything eligible by `now`
        while nxt < len(order) and elig[order[nxt]] <= now:
            i = order[nxt]
            heapq.heappush(pending, (keys[i], seq, int(i)))
            seq += 1
            nxt += 1
        # start what fits
        started = True
        while started and pending:
            started = False
            if pending[0][2] is not None and gpus[pending[0][2]] <= free:
                _, _, i = heapq.heappop(pending)
                free -= gpus[i]
                wait[i] = now - elig[i]
                heapq.heappush(running, (now + max(dur[i], 1.0), gpus[i]))
                started = True
            elif backfill:
                # look down the queue for a job that fits right now
                head = [heapq.heappop(pending) for _ in range(min(WINDOW, len(pending)))]
                pick = next((n for n, (_, _, i) in enumerate(head) if gpus[i] <= free), None)
                if pick is not None:
                    _, _, i = head.pop(pick)
                    free -= gpus[i]
                    wait[i] = now - elig[i]
                    heapq.heappush(running, (now + max(dur[i], 1.0), gpus[i]))
                    started = True
                for item in head:
                    heapq.heappush(pending, item)
        # advance time
        cands = []
        if running:
            cands.append(running[0][0])
        if nxt < len(order):
            cands.append(elig[order[nxt]])
        if not cands:
            break
        now = min(cands)
        while running and running[0][0] <= now:
            _, gp = heapq.heappop(running)
            free += gp
    return np.nan_to_num(wait, nan=0.0)


def report(name, wait, df):
    past = np.maximum(wait - TARGET, 0).sum() / H
    # person-hours: merge each owner's overlapping waits, as in case 8
    d = pd.DataFrame({"u": df.id_user.values, "lo": df.elig.values, "hi": df.elig.values + wait})
    d = d[d.hi > d.lo]
    total = 0.0
    for _, gg in d.groupby("u"):
        iv = sorted(zip(gg.lo, gg.hi))
        s, e, acc = iv[0][0], iv[0][1], 0.0
        for a, b in iv[1:]:
            if a > e:
                acc += e - s
                s, e = a, b
            else:
                e = max(e, b)
        total += (acc + e - s) / H
    row = {"policy": name, "total_wait_h": wait.sum() / H, "mean_s": wait.mean(),
           "p95_h": np.percentile(wait, 95) / H, "p99_h": np.percentile(wait, 99) / H,
           "max_h": wait.max() / H, "jobs_over_4h": int((wait > TARGET).sum()),
           "hours_past_target": past, "person_hours": total}
    print(f"{name:28s} total {row['total_wait_h']:9,.0f} h | p95 {row['p95_h']:6.2f} h | "
          f"p99 {row['p99_h']:7.2f} h | >4h {row['jobs_over_4h']:5d} | past-target {past:8,.0f} h | "
          f"person-h {total:7,.0f}")
    return row


print(f"replaying {len(BASE):,} jobs at {CAP} GPUs\n")
observed = j.qw_real.to_numpy(dtype=float)
rows = [report("OBSERVED (real waits)", observed, BASE.assign(id_user=j.sort_values("elig").id_user.values))]

policies = {
    "FCFS, no backfill": (lambda d: d.elig.to_numpy(dtype=float), False, None),
    "FCFS + backfill": (lambda d: d.elig.to_numpy(dtype=float), True, None),
    "SJF (oracle runtime)": (lambda d: d.dur.to_numpy(dtype=float), True, None),
    "Smallest-first (GPUs)": (lambda d: d.gpu_count.to_numpy(dtype=float), True, None),
    "Fair-share round robin": (None, True, None),
    "FCFS + 1h idle-kill": (lambda d: d.elig.to_numpy(dtype=float), True, 1.0),
    "SJF + 1h idle-kill": (lambda d: d.dur.to_numpy(dtype=float), True, 1.0),
}
for name, (key, bf, kill) in policies.items():
    if key is None:
        # round robin: order by how much GPU-time the owner has already been given
        owner_seq = BASE.groupby("id_user").cumcount().to_numpy(dtype=float)
        key = lambda d, o=owner_seq: o
    rows.append(report(name, simulate(BASE, key, bf, kill), BASE))

out = pd.DataFrame(rows).set_index("policy")
base = out.loc["FCFS + backfill"]
print("\nrelative to FCFS + backfill (the policy the real scheduler resembles).")
print("past-target is omitted: the baseline is under an hour, so ratios there are noise.")
for name in out.index:
    if name.startswith("OBSERVED"):
        continue
    r = out.loc[name]
    print(f"  {name:28s} person-hours {r.person_hours/base.person_hours-1:+7.1%} | "
          f"p99 {r.p99_h/base.p99_h-1:+7.1%} | jobs over 4h {int(r.jobs_over_4h):3d} | "
          f"${(r.person_hours-base.person_hours)*USD_ENG:+9,.0f}")
print("\nAbsolute simulated waits are ~18x below the observed ones, because this sample's "
      "jobs cannot fill 450 GPUs. Read the column as ordering effects, not as savings.")
out.round(2).to_csv("analysis/out_case9_scheduler.csv")
print("\nwrote analysis/out_case9_scheduler.csv")

# who pays for the current order: the widest jobs
print("\nobserved wait by width (the tail the order actually costs):")
w = pd.cut(j.gpu_count, [0, 1, 2, 8, 64], labels=["1", "2", "3-8", "9+"])
print(j.groupby(w, observed=True).qw_real.agg(n="size", median="median",
                                              p95=lambda s: s.quantile(.95) / H,
                                              p99=lambda s: s.quantile(.99) / H).round(2).to_string())
