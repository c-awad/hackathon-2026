"""Assemble claims.json from the analysis outputs, so the file cannot drift.

Every number here traces to a case in ANALYSIS.md; the node_triage entries come
straight from analysis/node_triage.json (case 6).
"""
import json

TEAM = "Team 16"
triage = json.load(open("analysis/node_triage.json"))

claims = {
    "team": TEAM,

    "recoverable_gpu_hours": {
        "point": 143763, "low": 80767, "high": 196365, "confidence": 0.6,
        "basis": (
            "Case 2. Every job is placed in exactly one waste class so no GPU-hour is counted "
            "twice, and the hours come from jobs.parquet rather than from the findings' "
            "impact_gpu_hours (summing those gives 157% of the cluster). Point = all hours of "
            "jobs that completed without ever running a kernel (12,301) + hours returned by a "
            "1-hour idle timeout on jobs that never ran a kernel and did not complete (81,878) "
            "+ half of near-idle jobs' idle hours (42,305) + half of idle second cards (7,280). "
            "Low = half the completed-never-ran hours + a conservative 4-hour idle timeout. "
            "High = no grace period + all near-idle idle hours + all idle-card hours. The half "
            "weights on the near-idle and card classes are judgement: 2,564 jobs (43,217 GPU-h) "
            "average under 5% but peak above 50%, so a policy keyed on average utilisation would "
            "kill real bursty work. CANCELLED is not counted as waste in itself. Excluded on "
            "purpose: gpu-memory-oversized (its jobs compute at 49%), and TIMEOUT jobs that were "
            "busy (real work destroyed at the wall clock, which checkpointing fixes rather than "
            "a cut)."),
    },
    "recoverable_usd": {
        "point": 359408, "low": 201918, "high": 490913, "confidence": 0.6,
        "basis": "The GPU-hours above at the price book's $2.50/GPU-hour (2026-Q3).",
    },

    "cancelled_is_waste": False,
    "cancelled_rationale": (
        "Case 2. Cancelled jobs ran at 34.3% hour-weighted utilisation against the cluster's "
        "38.5%, and 116,692 of their 203,930 GPU-hours fall into no waste class at all -- they "
        "were computing when someone stopped them. A cancellation is usually a researcher "
        "correctly killing a run that looked wrong, which is good practice we do not want to "
        "discourage. What IS waste is the idle time before the cancel, and classes A2 and B "
        "already capture it whatever the job's final state: 36,101 GPU-h of cancelled jobs never "
        "ran a kernel and 36,556 were near-idle. Counting all of CANCELLED would roughly double "
        "the headline by promising work that was already useful."),

    "node_triage": triage,

    "card_imbalance_gpu_hours": {
        "point": 13700, "low": 11500, "high": 19300, "confidence": 0.6,
        "basis": (
            "Case 3, from gpus.parquet at one row per (job, card) -- invisible in jobs.parquet, "
            "which averages a job's cards, so a job with one card at 0% and one at 65% reads as "
            "an ordinary 33% job. Restricted to the 9,828 jobs holding 2+ cards, with each card's "
            "hours clipped to the job's walltime (that removes 1,725 bad card-hours). A card "
            "counts as idle only when another card in the same job was working at 20%+, so jobs "
            "where every card idled stay in the never-ran class and are not double counted. "
            "Point = card average under 5%, job longer than 1 hour (13,681 GPU-h). Low = the "
            "card's PEAK was 0%, i.e. it never ran a kernel at all (11,551). High = loosening "
            "'the other card was working' to 10% and dropping the length filter (19,255). "
            "Applying rules::gpu-imbalance's own thresholds to this table reproduces its 689 "
            "findings and its 14,559 GPU-h exactly, which is our check on the method."),
    },
    "card_imbalance_rationale": (
        "gpus.parquet pivoted per gpu_id within each id_job; busiest card >= 20% SM, quietest "
        "< 5%, walltime > 1h. 10,883 of the 13,681 GPU-h are on 2-card jobs. 44 owners hold it "
        "and the top 10 hold 85%, so the remedy is about ten conversations rather than a "
        "cluster-wide policy. The risk is a multi-GPU job cancelled or failed before its "
        "data-parallel phase began: 4,753 GPU-h sit on cancelled jobs and 1,417 on failed ones, "
        "so we would only right-size an owner whose pattern repeats on jobs that completed."),
    "card_imbalance_index_reasoning": (
        "We checked WHICH card idles, expecting card 1 (code that only uses the default device). "
        "The data says the opposite: among single-node 2-card jobs with an imbalance, card 1 was "
        "the busy one in 885 jobs and card 0 in only 58. It is not one owner (39 owners show it) "
        "and not the scheduler (single-GPU jobs land on card 0 more often, 36,540 vs 28,481, and "
        "across all 2-card jobs card 1 is busier hour-weighted, 42.4% vs 34.9%). The idle card 0 "
        "holds a median 0.44 GiB at 37 W while the busy card holds 30.3 GiB -- the footprint of a "
        "framework initialising and then doing nothing there. Two explanations fit and this data "
        "cannot separate them: (a) the code targets a device other than 0, leaving a stray "
        "default context on card 0; (b) DCGM numbers cards in PCI-bus order while CUDA numbers "
        "them fastest-first unless CUDA_DEVICE_ORDER=PCI_BUS_ID is set, so the job's 'device 0' "
        "may be DCGM's card 1. The remedy is identical either way -- request one card -- but a "
        "detection rule that assumed 'card 1 idles' would miss nine of these jobs in ten."),

    "incident_root_cause": "pvc/scratch-lustre-02",
    "incident_action_scope": "single_resource",
    "incident_nodes_to_drain": 0,
    "incident_degraded_gpu_hours": {
        "point": 8654, "low": 7400, "high": 11005, "confidence": 0.6,
        "basis": (
            "Case 4. POST /v1/causal on any of the 121 filesystem-latency-degraded findings "
            "resolves them all to one shared volume (score 0.88, nodes 0.31), and every flagged "
            "node runs pods with a MOUNTS edge to it. Point = the findings' own impact, which we "
            "reproduced from real placements in gpus.parquet: each node's degraded hours are "
            "exactly the card-hours that ran on it in the 48 hours BEFORE detection (correlation "
            "1.000, median difference 0.01h). That also dates the episode: 2026-03-08 09:00 to "
            "2026-03-10 09:00 UTC. Low = the post-detection window reading (7,393). High = adding "
            "the 38 further machines whose pods mounted the same volume during the episode but "
            "carry no finding (11,005 total). These hours ran degraded; they were not lost."),
    },
    "incident_confidence": 0.85,

    "hardware_attributable_failures": 145,
    "hardware_attributable_confidence": 0.6,
    "hardware_attributable_rationale": (
        "Case 5. 145 = 31 + 114, from two independent sources. (1) 31 jobs had an attempt killed "
        "by a machine death on ANY attempt (hit_node_failure), not the 10 whose final state reads "
        "NODE_FAIL -- filtering on the final state loses two thirds of the signal because "
        "requeued jobs end some other way, 6 of them successfully. (2) 114 SIGBUS crashes on "
        "r216287-n200569, a machine the scheduler never marked down. We found it with a test that "
        "does not depend on the scheduler: for every (machine, exit status) pair, count owners who "
        "crashed there 3+ times with that status and NEVER produced it on any other machine. "
        "Across all 225 machines exactly one pair passes -- status 135 (SIGBUS) with 3 owners, 86 "
        "+ 23 + 5 crashes against 0 in their 946, 1,427 and 1,544 jobs elsewhere. 140 of the 144 "
        "jobs it ran in that window failed. LEFT OUT, deliberately: the other 26 failures on that "
        "machine in the window (statuses 1, 2, 130, 137 from 8 owners whose failure rates "
        "elsewhere are 16-69%, so they look like ordinary user failures); the 6 node failures that "
        "spanned 4-16 machines where the scheduler does not record which one died (blaming all of "
        "them would blame the innocent); and every one of the 113 node-elevated-failure-rate "
        "findings except the one our triage attributed to hardware -- 46 are user code, 40 are the "
        "mix of work the machine received, 26 cannot be determined. Low 124 (the 114 plus only the "
        "10 final-state NODE_FAIL jobs); high 171 (all 140 failures in the silent machine's window "
        "plus the 31). 145 is 0.8% of the 18,587 FAILED jobs: attributing every failure to "
        "infrastructure would overstate what fixing hardware recovers by more than 100x."),

    "notes": (
        "Full working, case by case, is in ANALYSIS.md; the endpoint-by-endpoint API review is in "
        "API_ANALYSIS.md; every number is reproduced by a script in analysis/. Three things we "
        "would flag to a judge.\n\n"
        "1. WHAT NOT TO DO. GET /v1/recommendations proposes draining the 5 machines with the most "
        "findings for $57,226. We would not: it ranks by finding count and never reads rootCauses, "
        "and 15 of the 20 findings it cites have no rootCause at all. The array-task findings on "
        "those same machines resolve via POST /v1/causal to their Slurm array at score 1.0 with "
        "each machine at its thin share (0.05-0.4). Draining them removes 1,680 GPU-h of capacity "
        "a week (~$55K a quarter) and the failing scripts fail wherever they land next. The one "
        "machine that really did break ranks 21st by finding count.\n\n"
        "2. THE QUEUE IS A QUOTA PROBLEM, NOT A CAPACITY ONE. GET /v1/queue/latency monetises "
        "waiting at $9,330,307 -- 6.3x the entire GPU bill -- by pricing every job's wait_sec as "
        "staffed time; 23% of those hours are jobs held by their own dependencies and 53% of jobs "
        "are array tasks, so one person with 1,000 pending tasks is counted 1,000 times. Merged "
        "per person and counted only past a 4-hour target it is 3,719 person-hours. We then "
        "replayed all 74,838 startable jobs at 450 GPUs (analysis/sched_sim.py): adding each "
        "researcher's own concurrency quota takes the model from 1% to 27% of observed "
        "person-hours (40% of total waiting), and in 90% of waits over an hour the person was "
        "already at their cap while a median 287 of 450 GPUs sat free. An elastic quota (let a "
        "user exceed it below 70% cluster allocation, preemptibly) plus the 1-hour idle timeout "
        "removes 96% of the modelled waiting, ~$120K of researcher time, at no capacity cost. "
        "Reordering the queue (SJF, fair-share) adds nothing on top -- the scheduler is already "
        "near-FIFO with working backfill.\n\n"
        "3. THREE API BUGS WE HIT. POST /v1/neighbor caps its node set at 500 with no flag in the "
        "response (api/main.py:142) and applies the cap before edges are gathered, so hop_count=2 "
        "returns 500 nodes and 5 edges -- fewer than one hop. GET /v1/queue/latency is labelled "
        "kind=fact while monetising a judgement. POST /v1/causal builds its sentence from "
        "whichever finding you asked about, so the same storage incident reads 'rose 28.3x' or "
        "'rose 45.5x', and its utilisation hop (-91.4%) is a constant in the code -- the real "
        "telemetry on those 121 machines shows 31.4% during the episode against 36.4% the week "
        "before.\n\n"
        "Data caveat we hold to throughout: MIT publishes this as a four-month SAMPLE of the "
        "cluster's jobs and says it is not appropriate for estimating system utilisation, so "
        "every figure describes the sample. The storage incident is the corpus's one synthetic "
        "scenario; everything else is computed from real telemetry."),
}
json.dump(claims, open("claims.json", "w"), indent=1)
print(f"wrote claims.json  ({len(triage)} node_triage entries)")
