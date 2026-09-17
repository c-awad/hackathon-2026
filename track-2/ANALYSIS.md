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
| 1 | Where the money goes | done |
| 2 | Recoverable spend, and whether CANCELLED is waste | next |
| 3 | Card imbalance | |
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

- **A quarter of all spend never ran a single GPU kernel: 147,547 GPU-h, $369K.**
  This is the cleanest waste pool in the data, because no reading of "useful work"
  covers a GPU that computed nothing. It cuts across every outcome: 53K cancelled,
  49K timed out, 23K completed (the work belonged on a CPU node), 21K failed.
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

> You spent $1.49M. $369K of it held GPUs that never ran a single calculation.
