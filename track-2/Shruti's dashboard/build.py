"""Build data.json for a three-tile dashboard built on one shared metric spine.

The spine is six buckets that every GPU-hour falls into, exactly once, so they
sum to the whole bill. Each bucket carries three readings of the same metric:

  tile 1  what it is now      -- hours, dollars, how busy the card actually was
  tile 2  how much can be cut -- the defensible slice, with the action and owner
  tile 3  the trade-off       -- what breaks if the cut is wrong, priced

Reads data/prepped/jobs.parquet and gpus.parquet only. rules::gpu-imbalance is
recomputed here rather than read from data/synthetic/findings.json, so the
dashboard runs on the prepped tables alone.

Cross-checks against track-2/ANALYSIS.md print at the end.
"""
import json
import os

import numpy as np
import pandas as pd

USD_GPU = 2.50
USD_ENG = 95.0
H = 3600.0
GRACE_POINT = 1.0          # hours of grace in the point estimate
WEEKS_PER_QUARTER = 13
DATA = os.environ.get("MGAI_DATA", "data")
OUT = os.environ.get("DASH_OUT", os.path.join(os.path.dirname(__file__), "data.json"))

GRACES = [0, 0.5, 1, 2, 4, 8, 12, 24]
THRESHOLDS = [0, 1, 2, 5, 10, 20]
GUARDS = [
    ("none", "No guard", "Kill on average utilization alone."),
    ("peak0", "Peak must be zero", "Only jobs whose busiest moment was also 0%."),
    ("peak20", "Peak under 20%", "Allows a brief spike, blocks sustained work."),
]


def usd(gpu_hours):
    return round(float(gpu_hours) * USD_GPU, 0)


def money(gpu_hours):
    """Dollars as display text, matching the formatting app.js uses."""
    v = float(gpu_hours) * USD_GPU
    a = abs(v)
    if a >= 1e6:
        return f"${v / 1e6:.2f}M"
    if a >= 1e3:
        return f"${round(v / 1e3):,.0f}K"
    return f"${v:,.0f}"


j = pd.read_parquet(f"{DATA}/prepped/jobs.parquet")
g = pd.read_parquet(f"{DATA}/prepped/gpus.parquet")

TOTAL = float(j.gpu_hours.sum())
TARGET = 0.20 * TOTAL
wall_h = (j.walltime_sec / H).clip(lower=1e-9)
busy_h = j.gpu_hours * j.sm_util_avg / 100
never_ran = (j.sm_util_avg == 0) & (j.sm_util_max == 0)
near_idle = ~never_ran & (j.sm_util_avg < 5)
completed = j.state_name == "COMPLETED"
bursty = (j.sm_util_avg < 5) & (j.sm_util_max >= 50)
never_touched = (j.sm_util_max == 0) & (j.max_gpu_mem_used == 0)


def after_grace(grace_h):
    """Fraction of a job's hours that fall after `grace_h` hours of wall clock."""
    return ((wall_h - grace_h).clip(lower=0) / wall_h)


# ------------------------------------------------------------ card imbalance
# rules::gpu-imbalance recomputed: 2+ cards, busiest card >= 20% SM, spread over
# 30 points, wall time over an hour. Invisible in jobs.parquet, which averages a
# job's cards, so a dead card beside a working one reads as an ordinary job.
gj = g.merge(j[["id_job", "walltime_sec", "gpu_count"]], on="id_job", how="left")
gj["card_h"] = np.minimum(gj.totalexecutiontime_sec, gj.walltime_sec).clip(lower=0) / H
multi = gj[gj.gpu_count >= 2].copy()
per_job = multi.groupby("id_job").smutilization_pct_avg.agg(["min", "max"])
spread_ok = (per_job["max"] >= 20) & ((per_job["max"] - per_job["min"]) > 30)
long_enough = j.set_index("id_job").walltime_sec.reindex(per_job.index) > H
imbalanced_jobs = per_job.index[spread_ok & long_enough]
# A card is idle when it sits more than 30 points below the busiest card in its
# own job -- the rule's measure, not "under 5%", which counts fewer hours.
multi["busiest"] = multi.id_job.map(per_job["max"])
idle_cards = multi[multi.id_job.isin(imbalanced_jobs)
                   & ((multi.busiest - multi.smutilization_pct_avg) > 30)]
imb_idle_by_job = idle_cards.groupby("id_job").card_h.sum()
IMB_IDLE = float(imb_idle_by_job.sum())

# ---------------------------------------------------------------- the spine
# One bucket per job, first match wins, so no hour is counted twice and the
# buckets sum to the full bill.
cls = pd.Series("productive", index=j.index)
cls[never_ran & completed] = "cpu_work"
cls[never_ran & ~completed] = "never_used"
cls[near_idle] = "barely_used"
cls[j.id_job.isin(imb_idle_by_job.index).values & (cls == "productive")] = "idle_card"
cls[(cls == "productive") & (j.state_name == "TIMEOUT") & (j.sm_util_avg >= 50)] = "killed_by_clock"

M = {k: (cls == k) for k in
     ("cpu_work", "never_used", "barely_used", "idle_card", "killed_by_clock", "productive")}
b_idle = (j.gpu_hours * (1 - j.sm_util_avg / 100))[M["barely_used"]]
c_idle = imb_idle_by_job.reindex(j.id_job[M["idle_card"]]).fillna(0)

# what an idle kill at the point-estimate grace returns from the never-used bucket
never_used_cut = float((j.gpu_hours * after_grace(GRACE_POINT))[M["never_used"]].sum())
grace_sweep = {str(gr): round(float((j.gpu_hours * after_grace(gr))[M["never_used"]].sum()), 0)
               for gr in GRACES}

low = 0.5 * float(j.gpu_hours[M["cpu_work"]].sum()) + float((j.gpu_hours * after_grace(4))[M["never_used"]].sum())
point = (float(j.gpu_hours[M["cpu_work"]].sum()) + never_used_cut
         + 0.5 * float(b_idle.sum()) + 0.5 * float(c_idle.sum()))
high = (float(j.gpu_hours[M["cpu_work"]].sum()) + float(j.gpu_hours[M["never_used"]].sum())
        + float(b_idle.sum()) + float(c_idle.sum()))


def bucket(key, name, full_name, plain, tile1_note, cut, cut_share_note, action, owner,
           confidence, risk, breaks, cost_hours, defence):
    """One spine row, read three ways.

    `name` is the short label the dashboard shows; `full_name` and `plain` carry the
    precise wording, which only the generated report needs.
    """
    m = M[key]
    h = float(j.gpu_hours[m].sum())
    bh = float(busy_h[m].sum())
    return {
        "key": key, "name": name, "full_name": full_name, "plain": plain,
        "now": {
            "jobs": int(m.sum()), "gpu_hours": round(h, 0), "usd": usd(h),
            "share_of_bill": round(h / TOTAL, 4),
            "busy_pct": round(bh / h * 100, 1) if h else 0.0,
            "note": tile1_note,
        },
        "cut": {
            "gpu_hours": round(float(cut), 0), "usd": usd(cut),
            "share_of_bucket": round(float(cut) / h, 4) if h else 0.0,
            "share_of_bill": round(float(cut) / TOTAL, 4),
            "basis": cut_share_note, "action": action, "owner": owner,
            "confidence": confidence,
        },
        "tradeoff": {
            "risk": risk, "what_breaks": breaks,
            "cost_gpu_hours": round(float(cost_hours), 0), "cost_usd": usd(cost_hours),
            "defence": defence,
        },
    }


spine = [
    bucket(
        "never_used", "Reserved, never used", "Held a GPU and never used it",
        "The job reserved a GPU and never ran a single calculation on it, then failed, timed out or was cancelled.",
        "These sit idle for days, not minutes. Hour-weighted, the typical one holds its GPU for "
        f"{(j.gpu_hours[M['never_used']] * wall_h[M['never_used']]).sum() / j.gpu_hours[M['never_used']].sum():,.0f} hours.",
        never_used_cut,
        f"Everything after a {GRACE_POINT:g}-hour grace period.",
        "End a job whose GPUs have sat at zero for an hour.",
        "Platform team — a scheduler policy, no researcher action needed.",
        "high",
        "low",
        "A job staging a large dataset, or running a long CPU preamble, that would have started "
        "computing after the grace period expired.",
        float(j.gpu_hours[M["never_used"]].sum()) - float((j.gpu_hours * after_grace(8))[M["never_used"]].sum()),
        "A peak-guarded rule has no false positives in this data: a job at 0% average and 0% peak "
        "never ran a kernel. Lengthening the grace to 8 hours is the priced safety margin.",
    ),
    bucket(
        "barely_used", "Barely used", "Barely touched the GPU",
        "The job did compute at some point, but averaged under 5% of the card.",
        "This is the bucket that looks cuttable and is not. Some of it is real work in short bursts.",
        0.5 * float(b_idle.sum()),
        "Half of the idle share of these hours, because the other half is probably real work.",
        "Investigate the biggest owners before writing any rule.",
        "Researchers who own the workflows, with platform support.",
        "low",
        "high",
        f"{int(bursty.sum()):,} jobs averaged under 5% but passed 50% at their busiest moment, and "
        f"{completed[bursty].mean():.0%} of them completed. A rule keyed on average utilization kills "
        "them in the middle of real work.",
        float(j.gpu_hours[bursty].sum()),
        "Key any rule on sustained zero, never on the average. Utilization is also a proxy: a job "
        "waiting on its data loader does real work at low occupancy.",
    ),
    bucket(
        "cpu_work", "Didn't need a GPU", "Finished without ever using the GPU",
        "The job completed successfully and never touched the GPU it was given. It is CPU work sitting in the GPU queue.",
        "The strongest evidence in the data: the work succeeded without the card.",
        float(j.gpu_hours[M["cpu_work"]].sum()),
        "All of it. The job already proved it does not need a GPU.",
        "Default these workflows to CPU nodes.",
        "Workflow owners — mostly a launcher default, not per-job.",
        "high",
        "low",
        f"{int((never_touched & (j.state_name == 'FAILED')).sum()):,} jobs crashed before reaching their "
        "GPU code. They look identical to this bucket but will need a card once the bug is fixed.",
        float(j.gpu_hours[never_touched & (j.state_name == "FAILED")].sum()),
        "Offload only jobs that completed without the GPU. Being wrong is cheap and visible: the job "
        "fails fast or runs slowly, and its owner resubmits with a GPU flag.",
    ),
    bucket(
        "idle_card", "Second GPU sat idle", "One card idle beside a working one",
        "A multi-GPU job where one card worked and another sat unused for the whole run.",
        "Invisible in the job table, which averages a job's cards. Only the per-card data shows it.",
        0.5 * float(c_idle.sum()),
        f"Half of the {IMB_IDLE:,.0f} idle card-hours. Right-sizing needs the owner to change code.",
        "Ask the owners to request one GPU instead of two.",
        "Researchers — this is a code change, not a setting.",
        "medium",
        "medium",
        "Nothing breaks if we are wrong, but nothing is recovered either. The saving only lands if the "
        "owner actually changes the request, and some code genuinely needs the second card later.",
        float(c_idle.sum()) - 0.5 * float(c_idle.sum()),
        "Treat it as a conversation with a handful of owners rather than a policy. Half-counted here "
        "for that reason.",
    ),
    bucket(
        "killed_by_clock", "Ran out of time", "Busy work destroyed at the time limit",
        "The job was computing hard when its time limit expired and the scheduler killed it.",
        "Real science, thrown away. It looks like waste in an outcome chart and is the opposite.",
        0.0,
        "Nothing. This is not a cut.",
        "Checkpointing, so a rerun resumes instead of restarting.",
        "Researchers and platform, together.",
        "not a cut",
        "not a cut",
        "Counting these hours as recoverable promises the CFO capacity that was already doing useful "
        "work. Cutting here does not free a GPU; it stops research.",
        float(j.gpu_hours[M["killed_by_clock"]].sum()),
        "Report as lost work in a separate column from savings. The remedy saves reruns, not capacity.",
    ),
    bucket(
        "productive", "Used normally", "Working normally",
        "Everything else: jobs that used the GPU they asked for.",
        "The majority of the bill, and the part a 20% cut must not touch.",
        0.0,
        "Nothing. This is the work the cluster exists for.",
        "Leave alone.",
        "--",
        "not a cut",
        "not a cut",
        "Any policy that reaches into this bucket is slowing research down, which is the one "
        "constraint the CFO was given.",
        0.0,
        "Every rule above is deliberately narrow so it cannot reach these hours.",
    ),
]

# ------------------------------------------------------------------- tile 1
cancel = j.state_name == "CANCELLED"
by_outcome = []
for name, grp in j.groupby("state_name"):
    h = float(grp.gpu_hours.sum())
    if h < 1:
        continue
    by_outcome.append({
        "outcome": {"COMPLETED": "Finished", "CANCELLED": "Stopped by its owner",
                    "TIMEOUT": "Ran out of time", "FAILED": "Crashed",
                    "NODE_FAIL": "Machine died"}.get(name, "Ended, reason unrecorded"),
        "raw": name, "jobs": int(len(grp)), "gpu_hours": round(h, 0), "usd": usd(h),
        "share": round(h / TOTAL, 4),
        "busy_pct": round(float((grp.gpu_hours * grp.sm_util_avg / 100).sum()) / h * 100, 1),
    })
by_outcome.sort(key=lambda r: -r["gpu_hours"])

user_hours = j.groupby("id_user").gpu_hours.sum().sort_values(ascending=False)
busy_total = float(busy_h.sum())
finished_busy = float(busy_h[completed].sum())

# Cumulative share of the bill as researchers are added, biggest first.
cum = (user_hours.cumsum() / TOTAL).reset_index(drop=True)
curve = [{"users": 0, "share": 0.0}] + [
    {"users": i + 1, "share": round(float(v), 4)} for i, v in cum.items()
]

tile1 = {
    "title": "Where the money went",
    "question": "Four months of GPU spending, in three numbers and one picture.",
    # The three figures the tab leads with. Nothing here needs a glossary.
    "kpis": [
        {"value": money(TOTAL), "label": "spent on GPU time",
         "sub": f"over four months, {len(j):,} jobs"},
        {"value": f"{busy_total / TOTAL * 100:.0f}\u00a2",
         "label": "of each dollar did any computing",
         "sub": "the rest paid for a card that sat idle"},
        {"value": f"{finished_busy / TOTAL * 100:.0f}\u00a2",
         "label": "of each dollar finished a job",
         "sub": "computing, and the job completed"},
    ],
    "headline": {
        "usd": usd(TOTAL), "gpu_hours": round(TOTAL, 0),
        "jobs": int(len(j)), "users": int(j.id_user.nunique()), "months": 4,
        "statement": f"{money(TOTAL)} of GPU time over four months, across {len(j):,} jobs "
                     f"from {j.id_user.nunique()} researchers.",
    },
    # Three stages of the same dollar: paid for, actually computing, turned into finished work.
    "funnel": [
        {"label": "We paid for", "gpu_hours": round(TOTAL, 0), "usd": usd(TOTAL), "cents": 100,
         "note": "Every GPU-hour the cluster handed out."},
        {"label": "The card was computing", "gpu_hours": round(busy_total, 0), "usd": usd(busy_total),
         "cents": round(busy_total / TOTAL * 100),
         "note": "The rest paid for a reserved card that was not calculating."},
        {"label": "It produced a finished job", "gpu_hours": round(finished_busy, 0),
         "usd": usd(finished_busy), "cents": round(finished_busy / TOTAL * 100),
         "note": "Busy and on a job that completed. The gap is the brief's 83%."},
    ],
    "by_outcome": by_outcome,
    "concentration": {
        "curve": curve,
        "markers": [{"users": k, "share": round(float(user_hours.head(k).sum()) / TOTAL, 4)}
                    for k in (5, 10, 20, 50)],
        "users_total": int(j.id_user.nunique()),
    },
    "reading": ("Read the buckets, not the outcomes. A cancelled job can be a researcher correctly "
                "killing a bad run, and a finished job can have barely touched its GPU. What the card "
                "was doing matters more than how the job ended."),
}

# ------------------------------------------------------------------- tile 2
cut_rows = [b for b in spine if b["cut"]["gpu_hours"] > 0]
by_key = {b["key"]: b for b in spine}
sure = sum(b["cut"]["gpu_hours"] for b in spine if b["cut"]["confidence"] == "high")
unsure = sum(b["cut"]["gpu_hours"] for b in spine if b["cut"]["confidence"] in ("medium", "low"))

tile2 = {
    "title": "Where to cut",
    "question": "How much of that comes back, and who has to do something?",
    "kpis": [
        {"value": money(point), "label": "we think we can cut",
         "sub": f"{point / TOTAL:.0%} of the bill, without slowing research down"},
        {"value": money(TARGET), "label": "the 20% goal we were given",
         "sub": "our best guess clears it" if point >= TARGET else "our best guess misses it"},
        {"value": money(sure), "label": "of that is the safe part",
         "sub": "GPUs that sat unused for days"},
    ],
    "total": {
        "low": {"gpu_hours": round(low, 0), "usd": usd(low), "share": round(low / TOTAL, 4),
                "basis": "Half the CPU-work bucket, plus a 4-hour-grace idle kill. Nothing else counted."},
        "point": {"gpu_hours": round(point, 0), "usd": usd(point), "share": round(point / TOTAL, 4),
                  "basis": "The per-bucket column on this tile, added up."},
        "high": {"gpu_hours": round(high, 0), "usd": usd(high), "share": round(high / TOTAL, 4),
                 "basis": "No grace at all, and every idle and idle-card hour counted."},
    },
    # The same wheel as tile 1, with the cut portion of each segment greyed out and
    # the reduced budget in the middle. Shares stay denominated in the whole bill so
    # the geometry is identical on both tiles.
    "wheel": {
        "before_usd": usd(TOTAL), "before_gpu_hours": round(TOTAL, 0),
        "cut_usd": usd(point), "cut_gpu_hours": round(point, 0),
        "after_usd": usd(TOTAL - point), "after_gpu_hours": round(TOTAL - point, 0),
        "cut_share": round(point / TOTAL, 4),
        "segments": [
            {"key": b["key"], "name": b["name"],
             "share_of_bill": b["now"]["share_of_bill"],
             "cut_share_of_bill": b["cut"]["share_of_bill"],
             "kept_share_of_bill": round(b["now"]["share_of_bill"] - b["cut"]["share_of_bill"], 4),
             "cut_usd": b["cut"]["usd"], "kept_usd": round(b["now"]["usd"] - b["cut"]["usd"], 0)}
            for b in spine
        ],
    },
    "target": {"gpu_hours": round(TARGET, 0), "usd": usd(TARGET), "share": 0.20},
    "clears_target": {"low": bool(low >= TARGET), "point": bool(point >= TARGET), "high": bool(high >= TARGET)},
    "verdict": ("The point estimate clears a 20% cut. The cautious reading does not, and falls "
                f"{money(TARGET - low)} short. Two thirds of the total is the near-certain part: GPUs that "
                "sat at zero for days."),
    "grace_sweep": {"hours": GRACES, "gpu_hours": grace_sweep,
                    "note": "The idle kill barely depends on the grace period, because these jobs sit "
                            "idle for days. Even a 24-hour grace returns most of the money."},
    "ranked": [
        {"rank": i + 1, "key": b["key"], "name": b["name"], "usd": b["cut"]["usd"],
         "gpu_hours": b["cut"]["gpu_hours"], "action": b["cut"]["action"],
         "owner": b["cut"]["owner"], "confidence": b["cut"]["confidence"],
         "risk": b["tradeoff"]["risk"]}
        for i, b in enumerate(sorted(cut_rows, key=lambda x: -x["cut"]["usd"]))
    ],
    "reading": ("Same six buckets as the previous section. The only change is the column: what each "
                "one gives back, and who has to do something for it to land."),
}

# ------------------------------------------------------------------- tile 3
# The interactive trade-off: every cell is an idle-kill policy someone could ship.
grid = []
index = {}
for gi, grace in enumerate(GRACES):
    frac = after_grace(grace)
    reachable = frac > 0
    for ti, thr in enumerate(THRESHOLDS):
        for key, _label, _hint in GUARDS:
            elig = (j.sm_util_avg <= thr) & reachable
            if key == "peak0":
                elig &= j.sm_util_max == 0
            elif key == "peak20":
                elig &= j.sm_util_max < 20
            returns = float((j.gpu_hours * frac)[elig].sum())
            destroyed = float((busy_h * frac)[elig].sum())
            hit_completed = elig & completed
            cell = {
                "g": gi, "t": ti, "guard": key,
                "jobs": int(elig.sum()),
                "returns_gpu_hours": round(returns, 0), "returns_usd": usd(returns),
                "busy_destroyed_gpu_hours": round(destroyed, 0), "busy_destroyed_usd": usd(destroyed),
                "completed_jobs_hit": int(hit_completed.sum()),
                "bursty_jobs_hit": int((elig & bursty).sum()),
                "bursty_gpu_hours_hit": round(float((j.gpu_hours * frac)[elig & bursty].sum()), 0),
            }
            grid.append(cell)
            index[(gi, ti, key)] = cell

# Definitions that swing the headline.
cancel_busy = float(busy_h[cancel].sum())
definitions = [
    {
        "id": "cancelled",
        "question": "Is a job its owner cancelled a waste of money?",
        "options": [
            {"label": "Yes, every cancelled hour", "gpu_hours": round(float(j.gpu_hours[cancel].sum()), 0),
             "usd": usd(j.gpu_hours[cancel].sum()), "verdict": "overstates"},
            {"label": "Only the hours the card sat idle",
             "gpu_hours": round(float(j.gpu_hours[cancel].sum()) - cancel_busy, 0),
             "usd": usd(float(j.gpu_hours[cancel].sum()) - cancel_busy), "verdict": "defensible"},
        ],
        "cost_gpu_hours": round(cancel_busy, 0), "cost_usd": usd(cancel_busy),
        "why": (f"Cancelled jobs ran at {(j.gpu_hours * j.sm_util_avg)[cancel].sum() / j.gpu_hours[cancel].sum():.1f}% "
                f"hour-weighted utilization against the cluster's {busy_total / TOTAL * 100:.1f}%. Cancelling is "
                "usually a researcher correctly killing a run that looked wrong — good practice, not waste. "
                "The idle time before the cancel is already counted in the buckets."),
    },
    {
        "id": "headline",
        "question": "How much of the bill is recoverable?",
        "options": [
            {"label": "Everything that did not become finished work",
             "gpu_hours": round(TOTAL - finished_busy, 0), "usd": usd(TOTAL - finished_busy),
             "verdict": "true but not recoverable"},
            {"label": "What a defensible policy frees", "gpu_hours": round(point, 0), "usd": usd(point),
             "verdict": "defensible"},
        ],
        "cost_gpu_hours": round(TOTAL - finished_busy - point, 0),
        "cost_usd": usd(TOTAL - finished_busy - point),
        "why": ("The first number is the brief's starting point and it is real. Promising it as a cut "
                "commits to recovering hours spent on work that finished, crashed for reasons a scheduler "
                "cannot fix, or was computing when it stopped."),
    },
    {
        "id": "weighting",
        "question": "What is the cluster's average utilization?",
        "options": [
            {"label": "Averaged across jobs", "pct": round(float(j.sm_util_avg.mean()), 1), "verdict": "not about money"},
            {"label": "Weighted by GPU-hours", "pct": round(busy_total / TOTAL * 100, 1), "verdict": "defensible"},
        ],
        "cost_gpu_hours": None, "cost_usd": None,
        "why": ("A third of the job records hold almost none of the compute, so counting jobs equally "
                "answers a different question from the one the CFO asked."),
    },
]

# Draining a suspect machine: reliability bought, capacity destroyed.
card = g[["id_job", "Node", "state_name", "id_user", "gpu_hours"]].copy()
per_node = card.groupby("Node").agg(jobs=("id_job", "nunique"), gpu_hours_served=("gpu_hours", "sum"),
                                    users=("id_user", "nunique"))
failed_rows = card[card.state_name == "FAILED"]
per_node["failures"] = failed_rows.groupby("Node").id_job.nunique().reindex(per_node.index).fillna(0).astype(int)
per_node["failure_rate"] = per_node.failures / per_node.jobs
top_owner = failed_rows.groupby(["Node", "id_user"]).id_job.nunique()
per_node["top_owner_share"] = (top_owner.groupby(level=0).max()
                               / per_node.failures.replace(0, np.nan)).reindex(per_node.index)
EXPOSURE_FLOOR = 50
by_count = per_node.sort_values("failures", ascending=False).head(10)
by_rate = per_node[per_node.jobs >= EXPOSURE_FLOOR].sort_values("failure_rate", ascending=False).head(10)


def node_rows(frame):
    out = []
    for name, r in frame.iterrows():
        share = None if pd.isna(r.top_owner_share) else round(float(r.top_owner_share), 3)
        out.append({"node": name, "jobs": int(r.jobs), "failures": int(r.failures),
                    "failure_rate": round(float(r.failure_rate), 4),
                    "gpu_hours_served": round(float(r.gpu_hours_served), 0), "users": int(r.users),
                    "top_owner_share_of_failures": share,
                    "one_owner_dominates": bool(share is not None and share >= 0.5)})
    return out


drain5 = 5 * 2 * 24 * 7 * WEEKS_PER_QUARTER
safe_cell = index[(GRACES.index(1), THRESHOLDS.index(0), "peak0")]
loose_cell = index[(GRACES.index(1), THRESHOLDS.index(5), "none")]
tile3 = {
    "title": "What it costs if we're wrong",
    "question": "Each cut assumes something. What breaks if the assumption turns out to be false?",
    "kpis": [
        {"value": money(sure), "label": "we are confident about",
         "sub": "these GPUs were switched on and never touched"},
        {"value": money(unsure), "label": "depends on a judgment call",
         "sub": "low usage might still be real work"},
        {"value": money(loose_cell["bursty_gpu_hours_hit"]),
         "label": "of real work we'd kill by mistake",
         "sub": "if we chased the bigger number and cut all low usage"},
    ],
    # Three sentences a non-specialist can act on. The full grid lives in the report.
    "risks": [
        {"claim": "Cut the GPUs that were never touched",
         "level": "safe",
         "amount": money(sure),
         "what_if_wrong": (f"None of these {safe_cell['jobs']:,} jobs ever ran a calculation, so there is "
                           "nothing to lose. This is the part to promise."),
         },
        {"claim": "Also cut anything under 5% usage",
         "level": "risky",
         "amount": money(loose_cell["returns_gpu_hours"]),
         "what_if_wrong": (f"Tempting, but it kills {loose_cell['completed_jobs_hit']:,} jobs that finished "
                           f"successfully, including {money(loose_cell['bursty_gpu_hours_hit'])} of work that "
                           "was busy in bursts and only looks idle on average."),
         },
        {"claim": "Reclaim the idle second GPU",
         "level": "needs people",
         "amount": money(by_key["idle_card"]["cut"]["gpu_hours"]),
         "what_if_wrong": ("No scheduler setting delivers this. Researchers have to change how their "
                           "code asks for GPUs, so treat it as a target, not a saving."),
         },
        {"claim": "Count jobs that ran out of time as waste",
         "level": "not a saving",
         "amount": money(float(j.gpu_hours[M["killed_by_clock"]].sum())),
         "what_if_wrong": ("These GPUs were working hard when the clock stopped them. The fix is longer "
                           "limits or checkpointing, which costs money rather than saving it."),
         },
    ],
    "simulator": {
        "graces": GRACES, "thresholds": THRESHOLDS,
        "guards": [{"key": k, "label": lb, "hint": h} for k, lb, h in GUARDS],
        "grid": grid, "default": {"g": GRACES.index(1), "t": THRESHOLDS.index(0), "guard": "peak0"},
        "note": ("A job at 0% average and 0% peak never ran a kernel, so a peak-guarded rule has no "
                 "false positives inside this data. Everything above zero trades savings for damage."),
    },
    "definitions": definitions,
    "nodes": {
        "exposure": {"min_jobs": int(per_node.jobs.min()), "max_jobs": int(per_node.jobs.max()),
                     "nodes": int(len(per_node)), "exposure_floor": EXPOSURE_FLOOR},
        "cluster_failure_rate": round(float((j.state_name == "FAILED").mean()), 4),
        "by_count": node_rows(by_count), "by_rate": node_rows(by_rate),
        "ranking_overlap": int(len(set(by_count.index) & set(by_rate.index))),
        "drain_cost": {"nodes": 5, "gpu_hours": drain5, "usd": usd(drain5), "weeks": WEEKS_PER_QUARTER},
        "why": ("Ranking machines by failure count and by failure rate gives two different lists, because "
                f"exposure runs from {int(per_node.jobs.min())} to {int(per_node.jobs.max()):,} jobs per "
                "machine. Before draining anything, check whether one researcher owns most of its failures."),
    },
    "limits": [
        {"limit": "No inside-the-job timeline",
         "consequence": "Utilization is one average and one peak per job. 'Idle the whole time' and "
                        "'idle on average' are indistinguishable unless the peak is also zero."},
        {"limit": "Utilization is a proxy for useful work",
         "consequence": "A job bound on its data loader or on talking to other machines does real work "
                        "at low occupancy. Low is a question, not a verdict."},
        {"limit": "Idle capacity is invisible where you would look for it",
         "consequence": "Telemetry starts and stops with a job, so an unallocated GPU emits nothing. None "
                        "of these figures describe time nobody booked."},
        {"limit": "This is a sample, not the whole cluster",
         "consequence": "MIT publishes four months of jobs and says it is not appropriate for estimating "
                        "system utilization. Every number describes this sample over this window."},
    ],
    "reading": ("Same six buckets again. The column now shows what we are assuming, and what it costs "
                "to be wrong about it — which is why the cautious total in the previous section is the "
                "honest one to promise."),
}

meta = {
    "title": "GPU Spend",
    "subtitle": ("Four months on one GPU cluster, in three questions. The workings, tables and "
                 "caveats are in the report."),
    "price_book": {"version": "2026-Q3", "usd_per_gpu_hour": USD_GPU, "usd_per_engineer_hour": USD_ENG},
    "cluster": {"nodes": int(len(per_node)), "gpus_per_node": 2, "jobs": int(len(j)),
                "users": int(j.id_user.nunique()), "gpu_hours": round(TOTAL, 0)},
    "sources": ["data/prepped/jobs.parquet", "data/prepped/gpus.parquet"],
    "rules_recomputed": {"gpu-imbalance": {"jobs": int(len(imbalanced_jobs)),
                                           "idle_gpu_hours": round(IMB_IDLE, 0)}},
    "caveat": ("MIT SuperCloud publishes this as a four-month sample of the cluster's jobs and says it is "
               "not appropriate for estimating system utilization. Figures describe the sample, not the "
               "cluster."),
}

out = {"meta": meta, "spine": spine, "tile1": tile1, "tile2": tile2, "tile3": tile3}
with open(OUT, "w") as fh:
    json.dump(out, fh, indent=1)
print(f"wrote {OUT}")

# --------------------------------------------------------------------- checks
spine_hours = sum(b["now"]["gpu_hours"] for b in spine)
spine_cut = sum(b["cut"]["gpu_hours"] for b in spine)
checks = [
    ("spine sums to the whole bill", round(spine_hours), round(TOTAL)),
    ("cut column sums to the point estimate", round(spine_cut), round(point)),
    ("total GPU-hours", round(TOTAL), 594004),
    ("gpu-imbalance jobs", len(imbalanced_jobs), 689),
    ("gpu-imbalance idle GPU-h", round(IMB_IDLE), 14559),
    ("finished without the GPU, GPU-h", round(float(j.gpu_hours[M["cpu_work"]].sum())), 12301),
    ("never used it, GPU-h", round(float(j.gpu_hours[M["never_used"]].sum())), 84896),
    ("barely used it, GPU-h", round(float(j.gpu_hours[M["barely_used"]].sum())), 85368),
    ("busy work killed by clock, GPU-h", round(float(j.gpu_hours[M["killed_by_clock"]].sum())), 44421),
    ("bursty jobs (avg<5, peak>=50)", int(bursty.sum()), 2564),
    ("point estimate GPU-h", round(point), 143763),
    ("low estimate GPU-h", round(low), 80767),
]
print("\ncheck                                       got     expected")
failures = 0
for name, got, want in checks:
    ok = abs(got - want) <= max(1, 0.01 * want)
    failures += 0 if ok else 1
    print(f"  {'ok ' if ok else 'OFF'} {name:<38} {got:>10,}  {want:>10,}")
print(f"\n{'all checks pass' if not failures else f'{failures} CHECK(S) FAILED'}")
