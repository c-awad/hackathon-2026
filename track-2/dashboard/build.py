"""Build dashboard/data.json -- every number the dashboard shows.

Runs in the same pinned image as the API, reads data/prepped/ and
data/synthetic/, and optionally the API on MGAI_URL for the Layer A/B calls the
dashboard quotes. Each tile carries its own drill-down rows so a viewer can get
from a dollar figure to job ids, node names and finding ids.

The reasoning behind every number is in track-2/ANALYSIS.md, case by case.
"""
import json
import os
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

USD_GPU = 2.50
USD_ENG = 95.0
TARGET_S = 4 * 3600
OFFSET = 1750862959
H = 3600.0
DATA = os.environ.get("MGAI_DATA", "data")
API = os.environ.get("MGAI_URL", "http://localhost:8000")
OUT = os.environ.get("DASH_OUT", "dashboard/data.json")


def api(path):
    """GET the facsimile API; the dashboard degrades to precomputed data if it is down."""
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=20) as r:
            return json.load(r)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        print(f"  ! {path}: {e}")
        return None


def api_post(path, body):
    """POST to the facsimile API (causal analysis). None if it is unreachable."""
    req = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        print(f"  ! POST {path}: {e}")
        return None


def causal_for(detector):
    """Ask /v1/causal about one finding from `detector` and keep the ranked culprits.

    This is the endpoint that resolves a correlated cluster of findings to the one
    resource underneath them -- the thing /v1/recommendations does not do.
    """
    fid = next((x["id"] for x in findings if x["detectorId"] == detector and x.get("rootCauses")), None)
    if not fid:
        return None
    r = api_post("/v1/causal", {"finding_id": fid})
    if not r or not r.get("findings"):
        return None
    c = r["findings"][0]
    return {"finding_id": fid, "detector": detector, "root_cause": c["root_cause"],
            "confidence": c.get("confidence"),
            "culprits": [{"name": x["node"], "type": x["type"], "score": x["score"]} for x in c["culprit"]],
            "chain": [{"resource": h.get("resource_id"), "metric": h.get("metric_name"),
                       "pattern": h.get("pattern"), "change_pct": h.get("change_pct")}
                      for h in c.get("causal_chain", [])]}


def usd(gpu_hours):
    return round(gpu_hours * USD_GPU, 0)


print("reading tables")
j = pd.read_parquet(f"{DATA}/prepped/jobs.parquet")
g = pd.read_parquet(f"{DATA}/prepped/gpus.parquet")
findings = json.load(open(f"{DATA}/synthetic/findings.json"))
f = pd.json_normalize(findings)
res = pd.read_parquet(f"{DATA}/synthetic/resources.parquet")
jx = j.set_index("id_job")
TOTAL = j.gpu_hours.sum()

# ---------------------------------------------------------------- tile 1: spend
wall_h = (j.walltime_sec / H).clip(lower=1e-9)
never_ran = (j.sm_util_avg == 0) & (j.sm_util_max == 0)
near_idle = ~never_ran & (j.sm_util_avg < 5)
imb = f[f.detectorId == "rules::gpu-imbalance"]
imb_idle = imb.set_index(imb["metadata.job_id"].astype("int64"))["metadata.idle_gpu_hours"].groupby(level=0).sum()
imbalanced = j.id_job.isin(imb_idle.index).values & ~never_ran & ~near_idle

cls = pd.Series("productive", index=j.index)
cls[never_ran & (j.state_name == "COMPLETED")] = "A1"
cls[never_ran & (j.state_name != "COMPLETED")] = "A2"
cls[near_idle] = "B"
cls[imbalanced] = "C"
cls[(cls == "productive") & (j.state_name == "TIMEOUT") & (j.sm_util_avg >= 50)] = "D"
j["cls"] = cls

busy = (j.gpu_hours * j.sm_util_avg / 100).sum()
completed_busy = (j.gpu_hours * j.sm_util_avg / 100)[j.state_name == "COMPLETED"].sum()

waterfall = [
    {"label": "Allocated to jobs", "gpu_hours": round(TOTAL, 0), "usd": usd(TOTAL),
     "note": "every GPU-hour the scheduler handed out"},
    {"label": "GPU actually busy", "gpu_hours": round(busy, 0), "usd": usd(busy),
     "note": "hours x average utilization: the cards were computing"},
    {"label": "Busy and the job finished", "gpu_hours": round(completed_busy, 0), "usd": usd(completed_busy),
     "note": "computing on work that produced a result"},
]

outcome = j.groupby("state_name").agg(jobs=("id_job", "size"), gpu_hours=("gpu_hours", "sum"))
outcome["busy"] = (j.assign(b=j.gpu_hours * j.sm_util_avg / 100).groupby("state_name").b.sum())
OUT_NOTE = {
    "COMPLETED": "produced a result",
    "CANCELLED": "someone stopped it -- often correctly",
    "TIMEOUT": "hit the wall clock; the work is destroyed",
    "FAILED": "crashed; almost always user code",
    "NODE_FAIL": "the scheduler said a machine died",
}
outcomes = []
other = {"jobs": 0, "gpu_hours": 0.0, "busy": 0.0}
for k, v in outcome.sort_values("gpu_hours", ascending=False).iterrows():
    if k.startswith("UNDECODED"):
        other["jobs"] += int(v.jobs); other["gpu_hours"] += v.gpu_hours; other["busy"] += v.busy
        continue
    outcomes.append({"label": k.title().replace("_", " "), "jobs": int(v.jobs),
                     "gpu_hours": round(v.gpu_hours, 0), "usd": usd(v.gpu_hours),
                     "busy_gpu_hours": round(v.busy, 0), "note": OUT_NOTE.get(k, "")})
if other["jobs"]:
    outcomes.append({"label": "Other terminal states", "jobs": other["jobs"],
                     "gpu_hours": round(other["gpu_hours"], 0), "usd": usd(other["gpu_hours"]),
                     "busy_gpu_hours": round(other["busy"], 0),
                     "note": "Slurm states 11 and 1024: terminal, with no documented meaning"}) 

bands = pd.cut(j.sm_util_avg, [-0.01, 0, 5, 20, 50, 80, 100],
               labels=["0%", "0-5%", "5-20%", "20-50%", "50-80%", "80-100%"])
util_bands = [{"label": (str(k) + " average" if str(k) == "0%" else str(k)), "jobs": int(v.jobs), "gpu_hours": round(v.gpu_hours, 0), "usd": usd(v.gpu_hours)}
              for k, v in j.groupby(bands, observed=True).agg(jobs=("id_job", "size"),
                                                              gpu_hours=("gpu_hours", "sum")).iterrows()]

# ------------------------------------------------------- tile 2: where to cut
def idle_after(grace_h):
    return j.gpu_hours * ((wall_h - grace_h).clip(lower=0) / wall_h)


A1, A2 = cls == "A1", cls == "A2"
B, C = cls == "B", cls == "C"
b_idle = (j.gpu_hours * (1 - j.sm_util_avg / 100))[B]
c_idle = imb_idle.reindex(j.id_job[C]).fillna(0)

# T1/T2 of case 2b: never opened the GPU at all vs loaded a context and idled
no_mem = j.max_gpu_mem_used == 0
t1 = never_ran & no_mem
t1_map = t1 & (j.job_type.isin(["LLMAPREDUCE:MAP", "LLSUB:BATCH"]))

sess = A2 & (j.job_type == "LLSUB:INTERACTIVE")
batch_idle = A2 & (j.job_type != "LLSUB:INTERACTIVE")


def drill_jobs(mask, n=12, extra=None):
    d = j[mask].nlargest(n, "gpu_hours")
    rows = []
    for _, r in d.iterrows():
        rows.append({"job": str(int(r.id_job)), "owner": f"u-{int(r.id_user)}", "node": r.primary_node,
                     "gpus": int(r.gpu_count), "gpu_hours": round(r.gpu_hours, 1), "usd": usd(r.gpu_hours),
                     "util_avg": round(r.sm_util_avg, 1), "util_peak": round(r.sm_util_max, 1),
                     "hours_held": round(r.walltime_sec / H, 1), "state": r.state_name,
                     "type": r.job_type, **(extra(r) if extra else {})})
    return rows


def finding_ids(detector, jobs=None, n=8):
    x = f[f.detectorId == detector]
    if jobs is not None:
        x = x[x["metadata.job_id"].isin(jobs)]
    return list(x.id.head(n))


actions = [
    {
        "id": "idle_kill",
        "title": "End allocations that sit at zero",
        "action": "Kill a job whose GPUs have shown 0% for an hour. 15,070 jobs held cards for a "
                  "median of 96 hours without ever running a single kernel.",
        "owner": "Scheduler policy (SRE on-call owns the timeout)",
        "gpu_hours": round(idle_after(1)[A2].sum(), 0),
        "low": round(idle_after(8)[A2].sum(), 0),
        "high": round(idle_after(0)[A2].sum(), 0),
        "effort": "low", "confidence": 0.85,
        "risk": "A job slow to start -- staging data, a long CPU preamble -- gets killed before it "
                "computes. Within this data a peak of exactly 0% means no kernel ever ran, so there "
                "are no false positives here; the exposure is future jobs that behave differently.",
        "risk_usd": 0,
        "sensitivity": [{"label": f"{gr}h grace", "gpu_hours": round(idle_after(gr)[A2].sum(), 0),
                         "usd": usd(idle_after(gr)[A2].sum())} for gr in (0, 1, 2, 4, 8)],
        "evidence_note": "jobs.parquet: sm_util_avg = 0 AND sm_util_max = 0 AND state != COMPLETED; "
                         "hours returned = gpu_hours x (walltime - grace) / walltime",
        "split": [{"label": "Interactive sessions left open", "gpu_hours": round(idle_after(1)[sess].sum(), 0)},
                  {"label": "Batch and other jobs", "gpu_hours": round(idle_after(1)[batch_idle].sum(), 0)}],
        "drill": drill_jobs(A2),
        "findings": finding_ids("rules::idle-interactive-session"),
        "api": "POST /v1/events/findings {\"detector_id\": \"rules::idle-interactive-session\"}",
    },
    {
        "id": "cpu_offload",
        "title": "Send CPU work to CPU nodes",
        "action": "Default the map-reduce and batch launchers to no GPU. Two thirds of LLMapReduce GPU "
                  "time never opened the GPU at all -- no kernel, no GPU memory, idle power draw.",
        "owner": "Research computing (launcher defaults) + the 10 owners below",
        "gpu_hours": round(j.gpu_hours[t1].sum(), 0),
        "low": round(j.gpu_hours[A1].sum(), 0),
        "high": round(j.gpu_hours[t1].sum() + j.gpu_hours[near_idle & no_mem].sum(), 0),
        "effort": "medium", "confidence": 0.7,
        "risk": "A job that crashed before reaching its GPU code looks identical. Offload only jobs "
                "that completed, or owners whose jobs are consistently like this. A wrong move is "
                "cheap: the job fails fast or runs slow and its owner resubmits with a GPU.",
        "risk_usd": usd(j.gpu_hours[t1 & (j.state_name == "FAILED")].sum()),
        "sensitivity": [
            {"label": "completed only (proven)", "gpu_hours": round(j.gpu_hours[A1].sum(), 0), "usd": usd(j.gpu_hours[A1].sum())},
            {"label": "never opened the GPU", "gpu_hours": round(j.gpu_hours[t1].sum(), 0), "usd": usd(j.gpu_hours[t1].sum())},
            {"label": "+ barely touched it", "gpu_hours": round(j.gpu_hours[t1].sum() + j.gpu_hours[near_idle & no_mem].sum(), 0),
             "usd": usd(j.gpu_hours[t1].sum() + j.gpu_hours[near_idle & no_mem].sum())},
        ],
        "evidence_note": "jobs.parquet: sm_util_max = 0 AND max_gpu_mem_used = 0; median watts_avg 25.8 "
                         "= an idle V100. Requests fit a 40-core/384 GiB node for 97% of these hours.",
        "split": [{"label": "LLMapReduce / batch launchers", "gpu_hours": round(j.gpu_hours[t1_map].sum(), 0)},
                  {"label": "Everything else", "gpu_hours": round(j.gpu_hours[t1 & ~t1_map].sum(), 0)}],
        "drill": drill_jobs(t1),
        "findings": finding_ids("rules::gpu-not-needed"),
        "api": "POST /v1/events/findings {\"detector_id\": \"rules::gpu-not-needed\"}",
    },
    {
        "id": "right_size",
        "title": "Right-size two-GPU requests that use one card",
        "action": "689 jobs held a second card that never worked while the first one did. Invisible in "
                  "the job table, which averages the cards.",
        "owner": "The 10 owners holding 85% of it (hashed)",
        "gpu_hours": round(c_idle.sum() + 0, 0),
        "low": 11500, "high": 19300,
        "effort": "medium", "confidence": 0.6,
        "risk": "A multi-GPU job cancelled or crashed before its parallel phase looks the same. "
                "4,753 of these GPU-hours are on cancelled jobs. Act only where an owner's pattern "
                "repeats on jobs that completed.",
        "risk_usd": usd(4753),
        "sensitivity": [{"label": "idle card peak 0%", "gpu_hours": 11500, "usd": usd(11500)},
                        {"label": "idle card under 5%", "gpu_hours": 13700, "usd": usd(13700)},
                        {"label": "loosest definition", "gpu_hours": 19300, "usd": usd(19300)}],
        "evidence_note": "gpus.parquet pivoted per gpu_id: busiest card >= 20% SM, quietest < 5%, "
                         "per-card hours clipped to the job's walltime. In 885 of 943 two-card jobs the "
                         "idle card is card 0, which holds a 0.44 GiB framework context.",
        "split": [{"label": "Two-card jobs", "gpu_hours": 10883}, {"label": "Wider jobs", "gpu_hours": 2798}],
        "drill": drill_jobs(C, extra=lambda r: {"idle_card_hours": round(float(imb_idle.get(int(r.id_job), 0)), 1)}),
        "findings": finding_ids("rules::gpu-imbalance"),
        "api": "POST /v1/events/findings {\"detector_id\": \"rules::gpu-imbalance\"}",
    },
]
for a in actions:
    a["usd"] = usd(a["gpu_hours"])
    a["low_usd"] = usd(a["low"])
    a["high_usd"] = usd(a["high"])
    a["share_of_spend"] = round(a["gpu_hours"] / TOTAL, 4)

recoverable = {
    "point": round(j.gpu_hours[A1].sum() + idle_after(1)[A2].sum() + 0.5 * b_idle.sum() + 0.5 * c_idle.sum(), 0),
    "low": round(0.5 * j.gpu_hours[A1].sum() + idle_after(4)[A2].sum(), 0),
    "high": round(j.gpu_hours[A1].sum() + idle_after(0)[A2].sum() + b_idle.sum() + c_idle.sum(), 0),
}
recoverable.update({f"{k}_usd": usd(v) for k, v in list(recoverable.items())})
recoverable["target_gpu_hours"] = round(0.2 * TOTAL, 0)
recoverable["target_usd"] = usd(0.2 * TOTAL)
recoverable["basis"] = ("Jobs that never ran a kernel (returned by an idle timeout or moved to CPU), "
                        "half of near-idle jobs, half of idle second cards. CANCELLED is not counted as "
                        "waste in itself -- only the idle time before the cancel.")

# ------------------------------------------- tile 3: what it costs if wrong
def node_cap(nodes, weeks):
    return len(nodes) * 2 * 24 * 7 * weeks


up = api("/v1/resources/underperforming?entity_type=node&limit=5")
top5 = [r["entity_id"] for r in up["rows"]] if up else [
    "r4605940-n772143", "r7317916-n772143", "r3974592-n172107", "r4144777-n172107", "r7317916-n303509"]
recs = api("/v1/recommendations")
drain_rec = next((r for r in recs["recommendations"] if r["id"] == "rec_drain_nodes"), None) if recs else None

triage = json.load(open("analysis/node_triage.json")) if os.path.exists("analysis/node_triage.json") else []
tri_by_node = {}
for t in triage:
    tri_by_node.setdefault(t["node"], []).append(t)

card = g[["id_job", "Node"]].drop_duplicates().join(jx[["state_name", "gpu_hours"]], on="id_job")
top5_rows = []
for n in top5:
    fr = f[f.resourceIds.map(lambda ids, rid=res.set_index("name")["id"].get(n): rid in ids)]
    arrays = fr[fr.detectorId == "rules::array-task-failure"]
    verdicts = [f"{t['cause']} (w{t['window']})" for t in tri_by_node.get(n, [])]
    on = card[card.Node == n]
    top5_rows.append({
        "node": n, "findings": int(len(fr)), "array_task_findings": int(len(arrays)),
        "verdicts": verdicts or ["not flagged"],
        "hardware_evidence": "none: no multi-owner crash signature, no node failure located here",
        "jobs": int(on.id_job.nunique()), "gpu_hours_served": round(on.gpu_hours.sum(), 0),
    })

incident_nodes = sorted(set(f[f.detectorId == "rules::filesystem-latency-degraded"]["metadata.node"]))
causal_volume = causal_for("rules::filesystem-latency-degraded")
causal_array = causal_for("rules::array-task-failure")
wrong = [
    {
        "id": "drain_top5",
        "title": "Drain the 5 machines with the most findings",
        "source": "GET /v1/recommendations -> rec_drain_nodes",
        "claimed_usd": drain_rec["estimated_savings"]["amount"] if drain_rec else 57225.93,
        "claimed_gpu_hours": drain_rec["estimated_savings_gpu_hours"] if drain_rec else 22890.4,
        "verdict": "Do not do this",
        "claim_label": "of savings", "in_chart": True,
        "cost_usd": usd(node_cap(top5, 13)),
        "cost_note": f"{node_cap(top5, 13):,} GPU-hours of capacity removed over a 13-week quarter, "
                     "and the failing scripts would fail on whatever machine they land on next.",
        "why": "The ranking counts findings per machine and never reads rootCauses. 664 of those "
               "findings resolve to failing Slurm arrays, not to the machines. Case 6 triage finds "
               "no hardware on any of the five. The one machine that really did break ranks 21st.",
        "causal": causal_array,
        "rows": top5_rows,
    },
    {
        "id": "drain_incident",
        "title": "Drain the 121 machines in the storage incident",
        "source": "rules::filesystem-latency-degraded x 121",
        "claimed_usd": usd(8654), "claimed_gpu_hours": 8654,
        "verdict": "Do not do this",
        "claim_label": "of savings", "in_chart": True,
        "cost_usd": usd(121 * 2 * 48),
        "cost_note": f"{121*2*48:,} GPU-hours over 48 hours -- 54% of the cluster -- and every machine "
                     "comes back to the same volume.",
        "why": "POST /v1/causal on any one of the 121 findings resolves them all to one shared volume, "
               "pvc/scratch-lustre-02, at score 0.88. One ticket to the storage team, not 121 drains. "
               "The findings' own degraded hours are exactly the GPU-hours those machines ran in the "
               "48 h before detection, which we reproduced from gpus.parquet (correlation 1.000).",
        "causal": causal_volume,
        "rows": [{"node": n, "role": "mounts pvc/scratch-lustre-02"} for n in incident_nodes[:12]],
    },
    {
        "id": "cancelled_as_waste",
        "title": "Count every cancelled job as waste",
        "source": "GET /v1/waste/breakdown -> CANCELLED 203,930 GPU-h",
        "claimed_usd": usd(203930), "claimed_gpu_hours": 203930,
        "verdict": "Overstates the target by about 2x",
        "claim_label": "of cancelled GPU time", "in_chart": True,
        "cost_usd": usd(116692),
        "cost_note": "116,692 GPU-hours of cancelled work was computing when it was stopped. Promising "
                     "that as a saving is promising work that was already useful.",
        "why": "Cancelled jobs ran at 34.3% hour-weighted utilization against the cluster's 38.5%. A "
               "cancellation is usually a researcher correctly killing a bad run. The waste is the idle "
               "time before the cancel, which the idle-timeout action already counts.",
        "rows": [{"label": "Idle before the cancel (counted)", "gpu_hours": 36101 + 36556},
                 {"label": "Idle second card (counted)", "gpu_hours": 14580},
                 {"label": "Was computing when stopped (not waste)", "gpu_hours": 116692}],
    },
    {
        "id": "queue_salary",
        "title": "Price queue waiting as engineer salary",
        "source": "GET /v1/queue/latency -> monetized",
        "claimed_usd": 9330306.65, "claimed_gpu_hours": None,
        "verdict": "6.3x the entire GPU bill",
        "claim_label": "of waiting, as salary", "in_chart": False,
        "chart_note": "kept out of the chart beside the others: this one is a number to correct, not capacity to destroy",
        "cost_usd": round(3719 * USD_ENG, 0),
        "cost_note": "Counted per person and only past a 4-hour target, waiting is 3,719 person-hours "
                     "(46 people, about 4.5 h each per week) -- an upper bound of $353K, not $9.3M.",
        "why": "The endpoint multiplies every job's wait_sec by $95. 53% of jobs are array tasks, so one "
               "person waiting on 1,000 tasks is counted 1,000 times; 23% of the hours are jobs held by "
               "their own dependencies, not queueing; and rules::queue-starvation's own text says this "
               "is elapsed time, not staffed time. Interactive sessions -- a person at a keyboard -- "
               "waited 0.8 hours in four months.",
        "rows": [{"label": "API: every job's full wait", "hours": 98214, "usd": round(98214 * USD_ENG)},
                 {"label": "Queue time only (from eligible)", "hours": 75334, "usd": round(75334 * USD_ENG)},
                 {"label": "Merged per person", "hours": 4997, "usd": round(4997 * USD_ENG)},
                 {"label": "Past a 4 h target, per person", "hours": 3719, "usd": round(3719 * USD_ENG)},
                 {"label": "Interactive sessions only", "hours": 1, "usd": 74}],
    },
]

# --------------------------------------------------------- hardware + triage
sig_node = "r216287-n200569"
hw = next((x for x in findings if x["detectorId"] == "rules::node-hardware-fault"), None)
hit = j[j.hit_node_failure]
hardware = {
    "scheduler_recorded_jobs": int(len(hit)),
    "scheduler_recorded_gpu_hours": round((hit.nodefail_wall_sec / H * hit.gpu_count).sum(), 0),
    "final_nodefail_jobs": int((hit.state_name == "NODE_FAIL").sum()),
    "silent_node": sig_node,
    "silent_failures": 114,
    "silent_window": [hw["metadata"]["window_start"][:10], hw["metadata"]["window_end"][:10]] if hw else [],
    "point": 145, "low": 124, "high": 171,
    "share_of_failed": round(145 / int((j.state_name == "FAILED").sum()), 4),
    "failed_jobs_total": int((j.state_name == "FAILED").sum()),
    "drain_cost_usd": round(5.9 * 48 * USD_GPU, 0),
    "jobs_crashed_after_evidence": 36,
    "finding_id": hw["id"] if hw else None,
    "note": "Three owners crashed on this machine with SIGBUS (exit status 135) and never produced that "
            "status on any other machine in four months: 86, 23 and 5 crashes against 0 in 946, 1,427 and "
            "1,544 jobs elsewhere. The scheduler never marked it down; 140 of its 144 jobs failed.",
}
triage_summary = (pd.DataFrame(triage).cause.value_counts().to_dict() if triage else {})

queue = {
    "p50_s": 0, "p95_h": 4.6, "p99_h": 14.8,
    "share_starting_within_a_minute": 0.588,
    "tail_share_of_hours": 0.31,
    "person_hours_past_target": 3719, "people_past_target": 46,
    "interactive_hours": 0.8,
    "idle_gpu_hours_during_contention": 80367,
    "share_idle_covers_demand": 0.62,
    "share_time_over_360_gpus": 0.006,
    "note": "Long waits barely track how full this sample is (correlation 0.15 between GPUs held and "
            "wait). They track bursts: one owner submitted 14,134 tasks of 16 seconds each on 2026-04-01, "
            "15% of all queue hours.",
}

meta = {
    "cluster": {"nodes": 225, "gpus_per_node": 2, "jobs": int(len(j)), "users": int(j.id_user.nunique()),
                "gpu_hours": round(TOTAL, 0), "usd": usd(TOTAL), "window_days": 125},
    "price_book": (api("/v1/price-book") or {"version": "2026-Q3", "usd_per_gpu_hour": USD_GPU,
                                             "usd_per_engineer_hour": USD_ENG}),
    "api_up": up is not None,
    "caveat": "MIT SuperCloud publishes this as a four-month sample of the cluster's jobs and says it is "
              "not appropriate for estimating system utilization. Every figure describes the sample. The "
              "storage incident (pvc/scratch-lustre-02) is synthetic; everything else is computed from "
              "real telemetry.",
    "sources": ["data/prepped/jobs.parquet", "data/prepped/gpus.parquet", "data/synthetic/findings.json",
                "GET /v1/efficiency/summary", "GET /v1/recommendations", "POST /v1/causal",
                "GET /v1/resources/underperforming", "GET /v1/queue/latency", "GET /v1/policies/rules"],
}

summary = api("/v1/efficiency/summary")
rules = api("/v1/policies/rules")
clear_rules = []
if rules:
    for r in rules.get("rules", rules.get("templates", [])) or []:
        if r.get("status") == "CLEAR":
            clear_rules.append({"id": r.get("id") or r.get("rule_id"), "name": r.get("name")})

out = {
    "meta": meta,
    "tile1": {"waterfall": waterfall, "outcomes": outcomes, "util_bands": util_bands,
              "api_summary": summary},
    "tile2": {"actions": actions, "recoverable": recoverable},
    "tile3": {"wrong": wrong},
    "hardware": hardware,
    "triage": {"summary": triage_summary, "entries": triage},
    "queue": queue,
    "clear_rules": clear_rules,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(out, open(OUT, "w"), indent=1, default=float)
print(f"wrote {OUT}")
print(f"  recoverable ${recoverable['point_usd']:,.0f} of ${meta['cluster']['usd']:,.0f}"
      f" (target ${recoverable['target_usd']:,.0f})")
for a in actions:
    print(f"  {a['id']:12s} ${a['usd']:>9,.0f}  [{a['low_usd']:,.0f} - {a['high_usd']:,.0f}]")
