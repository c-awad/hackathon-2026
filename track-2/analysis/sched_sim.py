"""The scheduler simulator, importable by both case9b_caps.py and the dashboard.

Replays every startable job in the dataset at 450 GPUs under a queue policy, with
per-user concurrency caps -- the constraint that turns out to explain most of the
observed waiting (see ANALYSIS.md, case 9b).

The dataset is MIT's published *sample* of the cluster's jobs, so the unsampled
work is absent and the model reproduces ~40% of the observed waiting. It therefore
understates every saving it reports.
"""
import heapq

import numpy as np
import pandas as pd

CAP_TOTAL = 225 * 2
H = 3600.0
TARGET = 4 * H
WINDOW = 600
LADDER = np.array([16, 32, 64])          # the quota rungs visible in the data


def _snap(v):
    d = np.abs(LADDER - v) / LADDER
    k = int(np.argmin(d))
    return int(LADDER[k]) if d[k] <= 0.10 else int(v)


class Sim:
    """Loaded job stream plus the inferred per-user caps."""

    def __init__(self, jobs: pd.DataFrame):
        j = jobs[jobs.time_start.notna()].copy()
        j["dur"] = j.walltime_sec.fillna(0).clip(lower=0)
        j["elig"] = j.time_eligible
        j["qw_real"] = (j.time_start - j.time_eligible).clip(lower=0)
        j["never_ran"] = ((j.sm_util_avg == 0) & (j.sm_util_max == 0)).values
        j = j.sort_values("elig").reset_index(drop=True)
        self.n_total = len(jobs)
        self.j = j
        self.ELIG = j.elig.to_numpy(dtype=float)
        self.GPUS = j.gpu_count.to_numpy(dtype=int)
        self.DUR0 = j.dur.to_numpy(dtype=float)
        self.NEVER = j.never_ran.to_numpy()
        self.UID = j.id_user.to_numpy()
        self.observed = j.qw_real.to_numpy(dtype=float)

        peak = {}
        for u, g in j.groupby("id_user"):
            ev = np.concatenate([
                np.stack([g.time_start.to_numpy(), g.gpu_count.to_numpy()], 1),
                np.stack([g.time_end.to_numpy(), -g.gpu_count.to_numpy()], 1)])
            ev = ev[np.argsort(ev[:, 0], kind="stable")]
            peak[u] = int(np.cumsum(ev[:, 1]).max())
        self.peak = peak
        self.caps_user = {u: _snap(v) for u, v in peak.items()}
        self.snapped = sum(1 for u, v in peak.items() if self.caps_user[u] != v)
        self.uidx = {u: k for k, u in enumerate(sorted(peak))}
        self.UI = np.array([self.uidx[u] for u in self.UID])
        self.USER_CAP = np.zeros(len(self.uidx))
        for u, k in self.uidx.items():
            self.USER_CAP[k] = self.caps_user[u]

    # ------------------------------------------------------------------ run
    def run(self, caps=True, idle_kill_h=None, elastic_below=None, cap_mult=1.0, sjf=False):
        dur = self.DUR0.copy()
        if idle_kill_h is not None:
            dur[self.NEVER] = np.minimum(dur[self.NEVER], idle_kill_h * H)
        cap_arr = self.USER_CAP * cap_mult if caps else np.full(len(self.uidx), np.inf)
        key = dur if sjf else self.ELIG
        ELIG, GPUS, UI = self.ELIG, self.GPUS, self.UI

        n = len(ELIG)
        wait = np.full(n, np.nan)
        free = CAP_TOTAL
        used = np.zeros(len(self.uidx))
        running, pending = [], []
        nxt = seq = 0
        now = ELIG[0]
        while nxt < n or pending or running:
            while nxt < n and ELIG[nxt] <= now:
                heapq.heappush(pending, (key[nxt], seq, nxt))
                seq += 1
                nxt += 1
            progress = True
            while progress and pending:
                progress = False
                held = [heapq.heappop(pending) for _ in range(min(WINDOW, len(pending)))]
                quiet = elastic_below is not None and (CAP_TOTAL - free) / CAP_TOTAL < elastic_below
                for pos, (_, _, i) in enumerate(held):
                    g, ui = GPUS[i], UI[i]
                    limit = np.inf if quiet else cap_arr[ui]
                    if g <= free and used[ui] + g <= limit:
                        held.pop(pos)
                        free -= g
                        used[ui] += g
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
                used[ui] -= g
        return np.nan_to_num(wait, nan=0.0)

    # -------------------------------------------------------------- metrics
    def person_hours(self, wait):
        """Merge each owner's overlapping waits: one person waiting once."""
        d = pd.DataFrame({"u": self.UID, "lo": self.ELIG, "hi": self.ELIG + wait})
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

    def summarize(self, name, wait):
        return {"policy": name, "total_h": round(wait.sum() / H, 1),
                "p50_s": round(float(np.percentile(wait, 50)), 1),
                "p90_h": round(float(np.percentile(wait, 90)) / H, 2),
                "p95_h": round(float(np.percentile(wait, 95)) / H, 2),
                "p99_h": round(float(np.percentile(wait, 99)) / H, 2),
                "over_4h": int((wait > TARGET).sum()),
                "past_target_h": round(float(np.maximum(wait - TARGET, 0).sum() / H), 1),
                "person_h": round(self.person_hours(wait), 1)}
