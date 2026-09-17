# Track 2 — Analysis log

Case-by-case working notes behind the dashboard and `claims.json`. Each case names
the script that produces its numbers; every script runs from `track-2/` against the
prepped data (`python3 analysis/<script>.py`).

**Conventions**

- Every figure is **GPU-hour weighted** unless it says otherwise, never row-weighted.
- Dollars use the price book `2026-Q3`: **$2.50 per GPU-hour**, $95 per engineer-hour.
- "Busy" hours are `gpu_hours × sm_util_avg / 100`. SM utilization is a proxy for
  useful work, not a measure of it.
- The data is a four-month **sample** of MIT SuperCloud, not the whole cluster.

| # | Case | Status |
|---|---|---|
| 1 | Where the money goes | done (corrected in case 2) |
| 2 | Recoverable spend, and whether CANCELLED is waste | done |
| 3 | Card imbalance | next |
| 4 | The shared-storage incident | |
| 5 | Hardware-attributable failures | |
| 6 | Node triage (113 elevated-failure-rate findings) | |
| 7 | The API's "drain the top 5 nodes" recommendation | |
| 8 | The queue tail, priced in engineer-hours | |

---

## Case 1 — Where the money goes

Script: `analysis/case1_money.py`

**Question.** How are the cluster's GPU-hours, and dollars, spent, broken down so a
non-engineer can see what's what?

### Headline

**594,004 GPU-hours, $1.49M, over four months. The GPUs were busy for 38.5% of the
time jobs held them.**

### By outcome

| Outcome | Jobs | GPU-h | Share | $ | Busy GPU-h |
|---|---|---|---|---|---|
| COMPLETED | 45,334 | 229,041 | 38.6% | $572,601 | 100,789 |
| CANCELLED | 9,290 | 203,930 | 34.3% | $509,824 | 69,956 |
| TIMEOUT | 1,544 | 107,952 | 18.2% | $269,879 | 43,717 |
| FAILED | 18,587 | 50,033 | 8.4% | $125,083 | 14,354 |
| NODE_FAIL | 10 | 2,028 | 0.3% | $5,070 | 57 |
| UNDECODED_11 / 1024 | 84 | 1,021 | 0.2% | $2,553 | 32 |

Only **17%** of held time was busy *and* on a job that completed (100,789 GPU-h).
That is the brief's "83% did not turn into completed work", and it is not the same
as 83% being recoverable.

### By utilization band

| Mean SM utilization | Jobs | GPU-h | Share |
|---|---|---|---|
| 0% (never ran a kernel) | 25,888 | 147,547 | **24.8%** |
| 0–5% | 4,538 | 38,527 | 6.5% |
| 5–20% | 11,085 | 68,437 | 11.5% |
| 20–50% | 18,808 | 131,676 | 22.2% |
| 50–80% | 10,350 | 66,426 | 11.2% |
| 80–100% | 4,180 | 141,390 | 23.8% |

### Outcome × utilization (GPU-h)

| Band | CANCELLED | COMPLETED | FAILED | NODE_FAIL | TIMEOUT | UNDECODED_11 |
|---|---|---|---|---|---|---|
| 0% | 53,176 | 22,989 | 20,611 | 927 | 48,950 | 894 |
| 0–5% | 19,868 | 14,131 | 2,284 | 823 | 1,415 | 5 |
| 5–20% | 21,446 | 32,507 | 4,765 | 278 | 9,429 | 13 |
| 20–50% | 54,544 | 63,234 | 10,016 | 0 | 3,773 | 110 |
| 50–80% | 15,982 | 42,840 | 3,930 | 0 | 3,674 | 0 |
| 80–100% | 38,913 | 53,340 | 8,427 | 0 | 40,710 | 0 |

### By job type

| Job type | Jobs | GPU-h | Share | Hour-weighted util |
|---|---|---|---|---|
| OTHER | 48,720 | 318,995 | 53.7% | 45.6% |
| LLSUB:BATCH | 22,198 | 204,564 | 34.4% | 36.4% |
| LLSUB:INTERACTIVE | 3,359 | 52,916 | 8.9% | **15.5%** |
| LLMAPREDUCE:MAP | 572 | 17,528 | 3.0% | 5.4% |

### By job width

| GPUs per job | Jobs | GPU-h | Share | Hour-weighted util |
|---|---|---|---|---|
| 1 | 65,021 | 294,562 | 49.6% | 29.0% |
| 2 | 8,472 | 137,114 | 23.1% | 38.3% |
| 3–8 | 958 | 63,855 | 10.7% | 50.9% |
| 9+ | 398 | 98,473 | 16.6% | 59.3% |

### Concentration

The top 5 users hold 29.8% of GPU-hours, the top 10 hold 44.5%, the top 20 hold 63.3%.
Users are hashed. The dashboard frames this as where capacity sits, not who to blame.

### What it means

- **A quarter of all spend sat at 0% average utilization: 147,547 GPU-h.** That band
  is too generous for a "never ran" claim, though (corrected in case 2): 6,001 of
  those jobs peaked above zero, so they did compute briefly. Jobs whose average
  **and** peak were both zero hold **97,196 GPU-h, $243K**. That strict figure is the
  cleanest waste pool in the data, because no reading of "useful work" covers a GPU
  that computed nothing.
- **Not every bad outcome is waste.** 40,710 GPU-h of timeouts ran at 80–100%
  utilization. That is real work destroyed at the time limit, and the remedy is
  checkpointing, not cutting. Likewise 38,913 GPU-h of cancellations were busy jobs,
  some of them deliberate kills. Calling all of CANCELLED waste overstates the total.
- **Wide jobs are the efficient ones per hour.** Hour-weighted utilization rises with
  width, from 29% on one GPU to 59% on nine or more. Counted by jobs instead, wide
  jobs look wasteful (the brief notes 59% of 9+ GPU jobs run under 5%). Both are
  true; only the hour-weighted view is about money.
- **Interactive sessions are 8.9% of spend at 15.5% utilization.** That points at an
  idle-timeout policy on interactive allocations (see `rules::idle-interactive-session`).

### Candidate CFO line

> You spent $1.49M. $243K of it held GPUs that never ran a single calculation.

---

## Case 2 — Recoverable spend, and whether CANCELLED is waste

Script: `analysis/case2_recoverable.py`

**Question.** How much of the $1.49M can be cut without slowing research, with a
range, and what happens to the headline depending on how CANCELLED is treated?

### Why the findings can't be summed

| Total | GPU-h | vs 594,004 allocated |
|---|---|---|
| Every job-scope finding's `impact_gpu_hours` | 536,211 | 90% |
| Distinct jobs carrying a finding, their real hours | 311,373 | 52% |

18% of flagged jobs carry more than one rule. And some rules claim a job's full
hours, whether or not the GPU was busy:

| Rule | Findings | Claimed GPU-h | Hour-weighted util of those jobs |
|---|---|---|---|
| `gpu-memory-oversized` | 108 | 107,009 | **48.8%** |
| `wallclock-kill` | 1,544 | 107,952 | 40.5% |
| `gpu-low-utilization` | 95 | 61,063 | 1.6% |
| `slow-cancel-of-idle-job` | 949 | 71,053 | 0.5% |
| `multi-node-low-utilization` | 63 | 34,819 | 7.0% |
| `gpu-imbalance` | 689 | 14,559 | 38.9% (claims idle cards only) |

`gpu-memory-oversized` claims 97% of its jobs' hours, but those jobs were computing
at 49%. Low GPU *memory* use is not idle *compute*. 38% of its hours are on jobs
above 50% utilization. We don't count it as recoverable.

`wallclock-kill` claims every timed-out hour as lost. That is true (the work must be
rerun), but it is not money a cut gives back. See class D below.

### Method: one class per job

Hours come from `jobs.parquet`, and findings are used only as labels. Each job lands
in exactly one class, and the first match wins.

| Class | Rule | Jobs | Job GPU-h | Share |
|---|---|---|---|---|
| **A1** | never ran (avg **and** peak = 0), COMPLETED | 4,817 | 12,301 | 2.1% |
| **A2** | never ran, did not complete | 15,070 | 84,896 | 14.3% |
| **B** | near-idle: avg < 5%, but computed at some point | 9,978 | 85,368 | 14.4% |
| **C** | card imbalance (`gpu-imbalance`), not in A/B | 689 | 31,613 (14,559 idle) | 5.3% |
| **D** | TIMEOUT at ≥ 50% util, not in A–C | 133 | 44,421 | 7.5% |
| — | productive or unclassified | 44,162 | 335,406 | 56.5% |

- **A1: move to CPU.** The job succeeded without touching the GPU. All of its
  hours are recoverable by placement (`gpu-not-needed`).
- **A2: idle-kill.** End a job whose GPUs have sat at 0% for a grace period. What
  that returns is the hours *after* the grace period:

  | Grace period | GPU-h returned | $ |
  |---|---|---|
  | 0 h | 84,896 | $212,239 |
  | 1 h | 81,878 | $204,695 |
  | 2 h | 79,278 | $198,194 |
  | 4 h | 74,617 | $186,543 |
  | 8 h | 66,477 | $166,191 |

  **The number barely depends on the grace period.** These jobs sit idle for days:
  the hour-weighted median wall time of a never-ran job is 96 hours. An 8-hour grace,
  which nobody could call aggressive, still returns $166K.

  A2 at a 1-hour grace, by outcome: 35,297 GPU-h cancelled, 29,558 timed out, 15,982
  failed. By job type: 27,778 interactive, 33,911 "other", 10,865 batch, 9,324
  map-reduce.
- **B: partial, and risky.** 84,610 of B's hours are idle, but **2,564 jobs (43,217
  GPU-h) averaged under 5% and peaked at 50% or more**, and 45% of them completed.
  These are bursty jobs doing real work, and a policy keyed on *average* utilization
  would kill them. We count only half of B, and only in the point estimate.
- **C: idle cards.** 14,559 GPU-h on the idle card of a multi-GPU job. Details in
  case 3. We count half, because right-sizing a 2-GPU request to 1 needs the owner to
  change code.
- **D: not a cut.** 44,421 GPU-h of busy work was destroyed at the time limit. The
  remedy is checkpointing, which saves reruns rather than capacity. We report it as
  lost work, never as recoverable.

### CANCELLED

**`cancelled_is_waste = false`.** Cancelled jobs ran at 34.3% hour-weighted
utilization, close to the cluster's 38.5%. Of their 203,930 GPU-h:

| Class | GPU-h |
|---|---|
| A2 never ran | 36,101 |
| B near-idle | 36,556 |
| C card imbalance | 14,580 |
| productive or unclassified | 116,692 (57%) |

A cancellation is usually a person correctly killing a run that looked wrong. What
*is* waste is the idle time *before* the cancel, and classes A2 and B already capture
that, whatever the job's outcome. Counting all of CANCELLED would add about 117K
GPU-h of work that was computing when it was stopped.

### The claim

| | How | GPU-h | Share | $ |
|---|---|---|---|---|
| **low** | half of A1 + A2 at 4 h grace | 80,767 | 13.6% | $201,918 |
| **point** | A1 + A2 at 1 h grace + ½ B + ½ C | 143,763 | 24.2% | $359,408 |
| **high** | A1 + A2 at 0 h + all of B idle + all of C idle | 196,365 | 33.1% | $490,913 |

The 20% target is 118,801 GPU-h ($297K). **The point estimate clears it, but the
low estimate doesn't.** The part we're sure of (A1 + A2, about $200K+) gets
two-thirds of the way. The rest depends on near-idle jobs, where a blunt policy
would hit real work.

### Cost of being wrong

- **Idle-kill (A2):** we have no intra-job time series. A job at exactly 0% average
  **and** 0% peak never ran a kernel, so within this data a peak-zero rule has no
  false positives. The risk is a job that is slow to start (data staging, a long
  CPU preamble) and would have computed after the grace period. Longer grace
  periods trade $5–10K per step for that safety.
- **Near-idle (B):** the real risk. 43K GPU-h of bursty jobs look idle on average.
  Any rule here must key on sustained zero, not on the average.
- **Caveat:** SM utilization is a proxy. A job that is bound on its data loader or
  on communication does real work at low SM occupancy.

### Candidate CFO line

> Over these four months, $360K of the $1.49M was recoverable (range $200K–$490K),
> about 24%. $200K of that is near-certain: GPUs that sat at zero for days.
