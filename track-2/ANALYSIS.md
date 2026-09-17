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

### Decisions so far

- **Don't drain the API's "top 5 underperforming nodes"** (`/v1/recommendations`,
  `rec_drain_nodes`, "$57K"). They are ranked by finding count, and those counts
  come from failing Slurm arrays (664 of their findings resolve to arrays through
  `rootCauses`). Case 6 finds no hardware on any of them: 7 windows are
  `user_code`, 1 `workload_mix`, 2 `cannot_determine`. None has a crash signature or
  a located node failure. Draining them would remove 1,680 GPU-h a week (about $55K
  a quarter) and save nothing, because the broken scripts would fail on other
  machines. The one machine that really was broken ranks 21st by finding count.
  See case 7.
- **Don't drain the 121 storage-incident nodes.** It is one volume,
  `pvc/scratch-lustre-02`. Draining would take 54% of the cluster offline. See
  case 4.
- **Do drain on a multi-owner crash signature.** `r216287-n200569` (SIGBUS) would
  have been caught six days earlier for about $700 of capacity. See case 5.
- **CANCELLED is not waste in itself.** Count only the idle time before the
  cancel. See case 2.
- **Do not reorder the queue to cut waiting.** The scheduler is already
  near-FIFO with working backfill, and 90% of long waits happen while the
  *same user* is at a per-user concurrency cap (16 / 32 / 65 GPUs) with a median
  of **287 of 450 GPUs free**. The fix is elastic caps and the idle timeout, not
  a different order. See case 9.
- **Prefer a credits pool to the elastic quota as the first step.** The elastic
  rule is reactive and untested under load; a pool gated on *predicted runtime*
  with a window of the mean job length cuts waiting 11-21% with near-zero measured
  harm to lenders. Do **not** forecast quotas from recent demand: it is too bursty
  (+1,316% waiting). See case 10.

| # | Case | Status |
|---|---|---|
| 1 | Where the money goes | done (corrected in case 2) |
| 2 | Recoverable spend, and whether CANCELLED is waste | done |
| 2b | Which GPU jobs could run on CPU instead | done |
| 3 | Card imbalance | done |
| 4 | The shared-storage incident | done |
| 5 | Hardware-attributable failures | done |
| 6 | Node triage (113 elevated-failure-rate findings) | done |
| 7 | The API's "drain the top 5 nodes" recommendation | done |
| 8 | The queue tail, priced in engineer-hours | done |
| 9 | Is the scheduler optimized? Would reordering help? | done |
| 9b | The same simulation with per-user caps modelled: now vs optimized | done |
| 10 | Predicted quotas and a credits pool: are they credible? | done |

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
  true; only the hour-weighted view is about money. **On finer bands the rise is not
  monotonic** (1: 29%, 2: 38%, 3-4: 42%, 5-8: 77%, 9-16: 67%, 17-64: 32%) -- the very
  widest jobs fall back, so "wider is better" holds to about 16 GPUs, not beyond.
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

---

## Case 2b — Which GPU jobs could run on CPU instead

Script: `analysis/case2b_cpu_offload.py`

**Question.** Do we know what each job needed, and can we tell which ones don't need a
GPU and could move to CPU nodes?

### What the data can and can't tell us

**It has the request:** `cpus_req`, `mem_req_mb` / `mem_req_total_mb`, `gres_req`
(`gpu:volta:N`), `timelimit`, `partition`, `constraints`, `job_type`.

**It doesn't have the program.** There is no command line, application or framework
name. So "needs a GPU" can't be read off the request, because every job here asked
for one. It has to be inferred from what the GPU did:

- `sm_util_max`, the peak compute utilization,
- `max_gpu_mem_used`, GPU memory ever allocated,
- `watts_avg`, where an idle V100 draws about 25 W.

### Tiers

| Tier | Test | Jobs | GPU-h | $ | Median W | Median GPU mem |
|---|---|---|---|---|---|---|
| **T1** never touched the GPU | peak 0% **and** 0 bytes GPU memory | 18,137 | 31,622 | $79,054 | 25.8 | 0 |
| **T2** CUDA context, no kernel | peak 0%, memory > 0 | 1,750 | 65,575 | $163,937 | 27.0 | 1.9 GiB |
| **T3** barely touched | peak ≤ 10%, < 1 GiB | 2,089 | 7,515 | $18,788 | 28.3 | 0.4 GiB |
| T4 used the GPU | everything else | 52,873 | 489,292 | $1,223,231 | 70.6 | 5.6 GiB |

T1 and T2 together are exactly the 97,196 never-ran GPU-h of case 2 (classes A1 + A2).
The power readings agree: T1 and T2 sit at idle-card wattage.

**T1 and T2 are different problems.**

- **T1 is a placement problem.** The program never opened the GPU. It is a CPU job
  in the GPU queue, whatever its outcome.
- **T2 is an idle problem.** The program loaded a GPU framework (1.9 GiB of CUDA
  context) and then never ran a kernel. It was written for a GPU and sat idle. Mostly
  it is interactive sessions (27.6K GPU-h) and "other" jobs (26.2K). The fix is
  case 2's idle-kill, not moving the job to CPU.

### Where T1 sits

| Job type | T1 GPU-h | Job type's total GPU-h |
|---|---|---|
| OTHER | 12,114 | 318,995 |
| **LLMAPREDUCE:MAP** | **11,528** | **17,528 (66%)** |
| LLSUB:INTERACTIVE | 5,158 | 52,916 |
| LLSUB:BATCH | 2,822 | 204,564 |

**Two-thirds of map-reduce GPU time never touched a GPU.** LLMapReduce is a
CPU-parallel launcher, so these look like CPU fan-out jobs that were given a GPU by
default. It is the single clearest offload target in the data.

T1 by outcome: 11,475 GPU-h cancelled, 10,171 timed out, 7,191 completed, 2,778 failed.

### Would they fit on a CPU node?

Among T1 + T2 jobs, the median request is 8 CPUs and 83 GiB, and the 99th
percentile is 40 CPUs and 350 GiB. **98.3% of the jobs (97.3% of the hours) fit on
one 40-core, 384 GiB node.**

That node size is an assumption. The data's `constraints` say `xeon-g6` (with some
`&6248`, the Xeon Gold 6248), which is a 2 × 20-core part, and the largest per-CPU
memory request is about 386 GB. The data doesn't describe the CPU-only partition,
so check this against the real hardware.

### A handful of owners hold most of it

- **35 owners** (each with at least 20 GPU jobs) had half or more of their GPU-hours
  never run a kernel. They account for **59,206 of the 97,196 GPU-h**.
- The top 10 owners hold 57% of T1 + T2 hours, and the top 20 hold 71%.
- **533 arrays** never ran a kernel in any task: 7,115 tasks, 12,573 GPU-h. Each is
  one submission script, so each is one fix.

The fix is a conversation or a default setting per workflow, not a cluster-wide rule.
Owners stay hashed on the dashboard.

### Confidence

| Set | GPU-h | $ | Confidence |
|---|---|---|---|
| T1 + T2 that **completed** (case 2's A1) | 12,301 | $30,751 | **high**: the work succeeded without the GPU |
| All of **T1** | 31,622 | $79,054 | **medium-high**: no GPU memory was ever allocated |
| T2 | 65,575 | $163,937 | **not an offload**: counted under idle-kill |
| T3 | 7,515 | $18,788 | **low**: may need the GPU briefly, and would run slower on CPU |

Completed T1 + T2 jobs are mostly tiny: the median wall time is under a minute, and
the 90th percentile is 46 minutes. Their hours sit in a few long runs (the 99th
percentile is 49 hours).

### Cost of being wrong

- **A job that failed before reaching its GPU code** (2,778 GPU-h of T1 failed) looks
  like T1 but needs a GPU once its bug is fixed. Offload only jobs that **completed**
  in T1, or owners whose jobs are **consistently** T1.
- **Moving a job to CPU doesn't make it free.** It frees the GPU, but the CPU cores
  still cost money, and the price book has no CPU rate. Report the saving as GPU
  capacity freed.
- **Getting it wrong is cheap and visible:** a job wrongly sent to CPU fails fast or
  runs slowly, and its owner resubmits with a GPU flag. That is much milder than
  idle-kill mistakes, which destroy work in progress.

### Bottom line

CPU offload is real but small: **$31K near-certain, up to $79K**. The larger lever
for the same never-ran hours is idle sessions (T2, $164K), which is case 2's
idle-kill. The dashboard should show both, with separate owners: placement defaults
for the map-reduce and batch launchers, and an idle timeout for interactive sessions.

---

## Case 3 — Card imbalance

Script: `analysis/case3_imbalance.py`

**Question.** How many GPU-hours sit on idle cards inside multi-GPU jobs whose other
cards are working, and why?

### Method

`jobs.parquet` averages across a job's cards, so a job with one card at 0% and one at
65% reads as an ordinary 33% job. This case uses `gpus.parquet` (one row per card per
job) instead, restricted to the **9,828 jobs with 2 or more cards**.

- **Per-card hours** are `totalexecutiontime_sec` clipped to the job's wall time,
  because some card rows report more runtime than their job had. Clipping removes
  1,725 card-hours.
- **A card counts as idle only if another card in the same job was working**
  (busiest card at 20% or more). Jobs where every card idled are case 2's never-ran
  jobs, and aren't counted again here.
- **17 requeued multi-card jobs** may mix rows from different attempts. They are
  left in, because they are too few to move the result.

### The rule reproduces exactly

Applying `rules::gpu-imbalance`'s condition (2+ cards, busiest ≥ 20%, spread > 30
points, wall time > 1 h) to `gpus.parquet` gives **the same 689 jobs** as the
finding, and the finding's `idle_gpu_hours` sum to **14,559**.

### Idle-card hours under different definitions

| Definition (all require another card ≥ 20%) | Cards | Jobs | GPU-h | $ |
|---|---|---|---|---|
| strict: card **peak** 0% (never ran a kernel) | 782 | 655 | 11,551 | $28,876 |
| card average 0% | 883 | 755 | 13,482 | $33,705 |
| card average < 5%, job > 1 h | 890 | 761 | 13,681 | $34,204 |
| the rule: card > 30 points below busiest | 768 | 689 | 14,558 | $36,395 |
| card average < 5%, busiest ≥ 10%, any length | | 1,632 | 19,255 | $48,138 |

Also calculated: had each flagged card worked at its busiest sibling's rate, the
shortfall is 9,198 GPU-h. That measures missing work rather than idle cards, so it
isn't used for the claim.

### The claim

| | GPU-h | $ | Definition |
|---|---|---|---|
| **low** | 11,500 | $28,750 | card peak 0% |
| **point** | 13,700 | $34,250 | card average < 5%, sibling ≥ 20%, job > 1 h |
| **high** | 19,300 | $48,250 | card average < 5%, sibling ≥ 10%, any length |

The low and point ends barely move with the definition. The high end loosens "the
other card was working" to 10%, which starts to overlap case 2's near-idle class B.

### Where it sits

- **By width:** 10,883 of the 13,681 GPU-h are on **2-card jobs**. Then 1,569 on
  4-card, 670 on 8-card and 494 on 32-card jobs.
- **By outcome:** 6,840 completed, 4,753 cancelled, 1,417 failed, 672 timed out.
  Completed jobs are the clean case: the work finished on the cards it used.
- **By job type:** batch 8,132, other 4,404, interactive 1,146. Only 7% are array
  tasks.
- **By owner:** 44 owners, and **the top 10 hold 85%**. This is about ten
  conversations, not a policy. No owner with 10 or more multi-card jobs is
  imbalanced on 80% of them, so it is a habit of particular workflows, not of whole
  teams.
- **Multi-node:** of 253 multi-node jobs with a working card, none had "one idle card
  on every node". 74 had whole nodes idle while others worked. That is a different
  failure: wasted nodes, not wasted cards.

### Which card idles, and why (`card_imbalance_index_reasoning`)

The obvious guess is code that only uses the default device, `cuda:0`. That would
leave **card 1** idle. **The data shows the opposite.** On single-node 2-card jobs
with an imbalance:

| | Jobs |
|---|---|
| card 1 busy, card 0 idle | **885** |
| card 0 busy, card 1 idle | 58 |

- **It isn't one owner.** 39 owners have a card-1-busy job and 15 have a
  card-0-busy job. One owner accounts for 504 of the card-1-busy jobs, but the
  pattern is widespread without them too.
- **It isn't the scheduler.** Single-GPU jobs land on card 0 *more* often (36,540
  against 28,481), and across all 2-card jobs, hour-weighted, card 1 is busier (42.4%
  against 34.9%).
- **The idle card 0 isn't empty.** Its median peak GPU memory is **0.44 GiB** at
  37 W, while the busy card 1 holds a median of 30.3 GiB. 0.44 GiB is the size of a
  GPU framework's context: something initialized the GPU on card 0 and then did all
  its work on card 1.

**Two explanations fit, and the data can't separate them:**

1. **A stray context.** The code targets one device other than 0, for example a
   hard-coded `cuda:1` or one process per rank where only rank 1 does work. The
   framework still opens a default context on device 0 at startup.
2. **Index mismatch.** DCGM numbers cards in PCI-bus order, while CUDA numbers them
   fastest-first unless `CUDA_DEVICE_ORDER=PCI_BUS_ID` is set. The job's "device 0"
   could be DCGM's card 1.

**Either way, the remedy is the same:** these jobs use one card, so they should
request one. The index pattern tells the SRE what to look for in the job scripts,
and it is why a rule that assumed "card 1 idles" would miss nine in ten of these
jobs.

### Cost of being wrong

- **Right-sizing to 1 GPU is safe for the job's compute:** the idle card did nothing
  and holds 0.44 GiB. The job might still need the second card's **memory** at
  startup, but the data shows it didn't use it.
- **The risk is a job that is imbalanced only in this run.** For example, a
  multi-GPU training job that failed or was cancelled before its data-parallel phase
  began, so only one card ever ran. 4,753 of the hours are on cancelled jobs, and
  1,417 on failed ones. Right-size an owner's jobs only when the pattern repeats and
  the imbalanced runs completed.
- **The stakes are small.** At $28K–$48K this is the smallest lever so far. It's
  worth a tile because it is **invisible in `jobs.parquet`**, which is the table most
  dashboards will read.

---

## Case 4 — The shared-storage incident

Script: `analysis/case4_storage.py`

**Question.** 121 nodes raised `filesystem-latency-degraded` at once. Is that 121
problems or one? What should be done, how many nodes should be drained, and how
many GPU-hours were affected?

**This is the one synthetic scenario in the corpus.** The volume, its `MOUNTS`
edges and all 121 findings carry `metadata.synthetic = true`. The jobs, placements
and utilization underneath are real.

### One cause, not 121

- **All 121 findings share a single root cause:** `pvc/scratch-lustre-02`, a
  400 TiB shared Lustre volume (`ReadWriteMany`).
- **`POST /v1/causal` on any of them** names the volume (score 0.88), with the
  nodes far behind at 0.31: *"pvc/scratch-lustre-02 degraded — filesystem p99
  latency rose …x, affecting 121 nodes"*.
- **The graph agrees.** Every one of the 121 nodes runs pods with a `MOUNTS` edge
  to the volume.
- **Timing:** detections span 30 minutes (2026-03-10 08:59–09:27 UTC). Per-node p99
  latency rose 28.3× to 45.5×.

### The episode window

The findings don't say when the 48-hour episode was. We rebuilt each node's
`impact_gpu_hours` from real placements in `gpus.parquet` under three candidate
windows:

| Window | Card-hours | Correlation with the finding's impact |
|---|---|---|
| detection → +48 h | 7,393 | 0.44 |
| **−48 h → detection** | **8,656** | **1.000** (median difference 0.01 h) |
| −24 h → +24 h | 8,531 | 0.69 |

**The episode is the 48 hours before detection: 2026-03-08 09:00 to 2026-03-10
09:00 UTC.** Each node's "degraded" hours are simply every card-hour that ran on it
in that window.

### Does the real telemetry show it?

| Cohort | Jobs | Hour-weighted util | Failed | Timed out | Median W |
|---|---|---|---|---|---|
| **121 nodes, episode** | 2,643 | **31.4%** | 30.3% | 1.0% | 29.8 |
| 121 nodes, the week before | 643 | 36.4% | 30.6% | 4.2% | 37.9 |
| 121 nodes, the week after | 381 | 30.6% | 20.2% | 11.5% | 39.6 |
| other nodes, episode | 1,414 | 44.9% | 27.2% | 2.2% | 41.8 |
| 38 mounting nodes without a finding, episode | 632 | 36.2% | 27.5% | 1.3% | 42.7 |

**The causal chain's second hop, `gpu_sm_utilization` "abrupt_drop −91.4%", isn't in
the real data.** Utilization on the 121 nodes was 31.4% during the episode, against
36.4% the week before and 30.6% the week after. That is a five-point dip, within
normal week-to-week variation, and the failure rate didn't move (30.3% against
30.6%). The nodes did run below the rest of the cluster in the same window (31.4%
against 44.9%), and at lower power, so a milder slowdown is consistent with the
data. A 91% collapse is not.

This is what you'd expect from a synthetic incident laid over real jobs: the
storage story is invented, and the jobs underneath carried on as they were. **The
causal chain's utilization hop is asserted, not measured**: in `api/main.py` it is a
constant (`change_pct=-91.4, z_score=-7.8`).

### What the API gets wrong

- **The quoted latency ratio depends on which finding you ask about.** `/v1/causal`
  builds its sentence from the *requested* finding's own `fs_latency_p99_ratio`, so
  the same incident is reported as anywhere from "rose 28.3x" to "rose 45.5x".
  A volume-level answer should quote one volume-level number.
- **The culprit list shows the first four nodes, always at 0.31.** That is a
  display choice, not evidence about those four.
- **"Affecting 121 nodes" understates the reach.** Pods mounting the volume were
  active on **159 nodes** during the episode. **38 of them have no finding**, and
  they carried 632 jobs and 2,350 card-hours. Either the detector missed them, or
  they weren't affected, which would undercut "the volume did it". The data can't
  tell which.

### The answer

| Field | Value |
|---|---|
| `incident_root_cause` | `pvc/scratch-lustre-02` |
| `incident_action_scope` | `single_resource` |
| `incident_nodes_to_drain` | **0** |
| `incident_degraded_gpu_hours` | point **8,654**, low 7,400, high 11,000 |
| `incident_confidence` | 0.85 |

**Degraded hours.**

- **The point** is the findings' own figure, which we reproduced exactly from real
  placements.
- **The low end** allows for the episode boundaries being uncertain: the
  post-detection reading gives 7,393.
- **The high end** adds the 38 mounting nodes without a finding (11,005 in total).

At $2.50 per GPU-hour that is $21.6K, with a range of $18.5K to $27.5K. These hours
ran *degraded*; they weren't lost. The real telemetry suggests the degradation was
mild.

### Cost of being wrong

**Draining the 121 nodes is the expensive mistake.** It removes 11,616 GPU-h of
capacity over 48 hours ($29K), **54% of the cluster**, and it fixes nothing: every
drained node would come back to the same slow volume.

The right action is one ticket to the storage team for one volume. In the
meantime, route latency-sensitive jobs away from `scratch-lustre-02`, not away from
the machines.

If the volume *isn't* the cause, the cost of acting on it is small: one storage
investigation. The evidence against the volume is also strong: one shared
dependency, every flagged node mounting it, and detections within 30 minutes. So
the asymmetry favors the single-resource answer.

### Candidate CFO line

> A storage slowdown looked like 121 broken machines. It was one volume. Fix the
> volume; draining the machines would have taken half the cluster offline for two
> days and fixed nothing.

---

## Case 5 — Hardware-attributable failures

Script: `analysis/case5_hardware.py`

**Question.** How many failed jobs were genuinely caused by faulty hardware, and
which machines were responsible?

**Exit status** is `exit_code // 256`. Among FAILED jobs the common statuses are 1
(14,218), 2 (1,529), 137 SIGKILL (1,228), 134 SIGABRT (453), 130 (411), 127 (382),
135 SIGBUS (129) and 139 SIGSEGV (95). A single exit code can't say whether the code
or the machine was at fault. A *pattern* can.

### Source 1: what the scheduler recorded

| | |
|---|---|
| Jobs that hit a node failure on any attempt | **31** |
| Failed attempts | 39 |
| Jobs whose *final* state is NODE_FAIL | 10 |
| Final states of the 31 | NODE_FAIL 10, CANCELLED 7, COMPLETED 6, FAILED 5, TIMEOUT 3 |
| Failures located to one machine | 25 |
| GPU-h lost in failed attempts | **7,772** |

**Filtering on `state_name == NODE_FAIL` finds 10 of the 31.** The other 21 were
requeued and ended some other way, 6 of them successfully.

**The job's machine is usually not the one that died.** Of the 25 located failures,
19 happened on a different machine from the job's `primary_node`. The docs count 18
against the final attempt's machine; the small difference comes from `primary_node`
being the first node in the list. Two machines died twice: `r4683026-n772143` and
`r810901-n948219`.

Six failures spanned 4 to 16 machines, and the scheduler doesn't record which one
died. We don't blame any of them.

### Source 2: a machine that broke silently

**The test.** For every (machine, exit status) pair, count the owners who crashed
there with that status at least 3 times and **never** produced it on any other
machine. One owner fitting that test is a habit of their code on that machine. Two
or more unrelated owners point at the machine.

**Across all 225 machines, exactly one pair passes:**

| Machine | Status | Owners | Crashes |
|---|---|---|---|
| **`r216287-n200569`** | **135 (SIGBUS, bus error)** | **3** | **114** |

Five other pairs have a single owner, which reads as user code.

This independently reproduces `rules::node-hardware-fault`. Over its window
(2026-02-27 to 03-07):

- **The machine ran 144 jobs and 140 of them failed.**
- **Three owners' SIGBUS crashes:** 86 + 23 + 5, against 0 SIGBUS crashes in their
  946, 1,427 and 1,544 jobs on other machines.
- **The other 26 failures** (statuses 1, 2, 130, 137) came from 8 owners whose usual
  failure rate elsewhere is 16% to 69%. They look like ordinary user failures, not
  the machine.
- **The SIGBUS crashes came in two bursts**, 85 on March 1 and 29 on March 5. There
  was no SIGBUS on this machine before or after. The machine kept failing jobs later
  (for example 43 of 51 on March 10), but with other statuses and without the
  multi-owner signature.

### Why the obvious methods miss it

- **The scheduler never marked it down.** It has zero NODE_FAIL records, so it
  kept receiving work.
- **Ranking by raw failures puts it 5th.** The four machines above it (366, 325,
  288 and 286 failures) are high-volume machines where users' own failures pile up.
- **The rate rule does flag it, with no cause.** By failure *rate* it is 2nd, and
  `node-elevated-failure-rate` fired on it (p = 2e-54 for 2026-02-25). But that rule
  fires on 87 machines and deliberately says nothing about why.
- **Single exit codes can't separate code from machine.** 129 SIGBUS failures
  cluster-wide look like user bugs one at a time.

### How early it could have been caught

The first SIGBUS came on 03-01 at 12:08, and a **second, unrelated owner** crashed
the same way on 03-01 at 19:16. From that moment the multi-owner test had its
evidence. After that point, **36 more jobs** crashed with SIGBUS before the finding
was raised on 03-07.

**Draining the machine at the second owner's crash** would have removed about 5.9
days of one 2-GPU node: **281 GPU-h, about $700 of capacity**. That is cheap next to
36 crashed jobs and the researcher time behind them. A two-owner signature rule is
worth running on every machine.

### The count

| | Failed jobs | GPU-h lost |
|---|---|---|
| Scheduler-recorded (any attempt killed by a node failure) | 31 | 7,772 |
| Silent machine, SIGBUS signature | 114 | 76.6 (whole window, 140 failures) |
| **Point** | **145** | **about 7,850 ($19.6K)** |

- **Low: 124.** The 114 SIGBUS crashes plus the 10 jobs whose final state is
  NODE_FAIL, counting only failures that nothing recovered from.
- **High: 171.** All 140 failures on the silent machine in its window, plus the 31
  scheduler-recorded jobs. This assumes the broken machine also caused some of the
  non-SIGBUS failures, which the owners' base rates argue against.

**`hardware_attributable_failures = 145`**, with confidence 0.6. That is **0.8% of
the 18,587 FAILED jobs**. Almost all failures on this cluster are user code, and
counting every failure as infrastructure would overstate what fixing hardware
recovers by more than 100×.

### Cost of being wrong

- **Too many false alarms would drain healthy machines.** Draining a 2-GPU machine
  costs 48 GPU-h a day ($120). The two-owner signature fired exactly once in four
  months, so false-alarm drains would be rare and cheap.
- **Missing a real fault costs far more.** This one sat in service for six days and
  crashed 36 more jobs after the evidence was in.
- **Blaming the machine a job finished on is the other mistake.** It picks the wrong
  machine for 19 of 25 scheduler-recorded failures. Use `nodefail_nodes`.

### Candidate CFO line

> Hardware caused under 1% of failures. One machine broke silently and failed 140 of
> 144 jobs over a week; a $700 drain would have caught it six days sooner.

---

## Case 6 — Node triage

Script: `analysis/case6_triage.py`. Outputs: `analysis/node_triage.json` (the
`claims.json` entries) and `analysis/out_case6_triage.json` (every number).

**Question.** `rules::node-elevated-failure-rate` fired 113 times on 87 machines.
Why did each one fire: `hardware`, `user_code`, `workload_mix`, or
`cannot_determine`?

### Reproducing the rule first

Before judging a finding we rebuilt the counts it was computed from. The rule
evaluates **consecutive 14-day windows anchored at the first job** (2026-02-25 about
22:00 UTC). It counts jobs by **`time_end`**, attributes them to a machine through
**`gpus.parquet`'s `Node`** (not `primary_node`), and counts `state_name == FAILED`
as a failure.

With that definition, **112 of 113 findings reproduce exactly** (`metadata.jobs`
and `metadata.failed`). The exception, `r8473362-n410412` in window 4, is short
by one job that didn't fail (115 against 116), most likely a requeued job whose card
rows sit on another attempt's machine.

**Window index** = `(time_end − first job start) // 14 days`. It runs from 0
(2026-02-25) to 8 (2026-06-17), matching each finding's `window_start`.

### The tests, compared like with like

For each (node, window), using only jobs that finished in that window:

1. **Machine signature (hardware).** An exit status (`exit_code // 256`) that
   **two or more owners** hit on this machine at least twice, and on **no other
   machine in four months**, or two or more node failures located here
   (`nodefail_nodes`, `nodefail_exact`).
2. **One person (user_code).** All of the following must hold:
   - the top owner holds **≥ 60%** of the failures,
   - **everyone else** on the machine fails at a rate not above the cluster's
     (one-sided binomial, p ≥ 0.05),
   - the owner's failures follow them, either on **other machines in the same
     window** (at least half their rate here, with ≥ 5 jobs there) or in **the same
     arrays' tasks on other machines** (sibling failure rate at least half their
     rate here, with ≥ 5 siblings).

   Arrays are the cleanest comparison: identical scripts on different machines.
3. **The work it received (workload_mix).** No owner dominates. The expected count
   is Σ over owners of (their jobs here × their own FAILED rate on other machines in
   the same window). If observed failures aren't significantly above that (Poisson,
   p ≥ 0.05, with at least 60% of jobs having a baseline), the machine simply
   received failure-prone work.
4. **Everything else is cannot_determine,** with the specific reason: no baseline
   for the dominant owner, others on the machine also elevated, or excess failures
   spread over several owners without a signature.

We avoided two traps from `docs/rules.md`:

- "Whoever owns most failures" isn't a test on its own, so we always check the rest
  of the machine.
- "Does this person fail elsewhere" isn't a test unless the work is comparable,
  which is why we use array siblings and the same window.

### Results

| Cause | Findings | Failed jobs | Verdict |
|---|---|---|---|
| `user_code` | **46** | 2,913 | `no_action` on the machine (talk to the owner) |
| `workload_mix` | **40** | 841 | `no_action` |
| `cannot_determine` | **26** (23%) | 1,366 | `monitor` |
| `hardware` | **1** | 188 | `act` |

**The one hardware verdict** is `r216287-n200569` in window 0, case 5's silent
SIGBUS machine: status 135 × 3 owners. **The same machine in window 3 comes out
`user_code`**: 20 of 33 failures from one owner whose array siblings elsewhere failed
180 of 180. After the SIGBUS episode, the machine's failures were ordinary user
failures.

**Examples of reasoning** (every entry names its columns and numbers):

- *user_code:* `r3974592-n172107` in window 0 had 106 of 139 jobs fail, against a
  cluster rate of 0.291. `u-11631751931` holds 94% of the failures (100 of 116 here)
  and failed 943 of 3,451 on other machines. Their array siblings elsewhere failed
  215 of 227, and everyone else on the machine failed 6 of 23 (p = 0.70, not
  elevated).
- *workload_mix:* `r3974592-n303509` in window 0 had 47 of 112 jobs fail. Six owners
  were failing, and the top one held 53%. From each owner's own rate elsewhere,
  42.8 failures were expected against 47 observed (p = 0.28).
- *cannot_determine:* `r810901-n772143` in window 8 had 70 of 89 jobs fail. One
  owner holds 80%, but the others on the machine also failed 14 of 17, so the
  machine isn't cleared. There was no signature and no node failure.

### The ones worth a second look

Three `cannot_determine` findings lean toward the machine:

| Node, window | Failed | Why it leans toward the machine |
|---|---|---|
| `r7317916-n172107`, w7 | 193/234 | 4 owners fail here at 2× or more their own rate. The top owner went 55/55 here against 6/177 elsewhere in the same window, **and their array siblings elsewhere succeeded 11/11**. Two bursts, on June 7 (89/93) and June 9 (68/75). All exit status 1, so there is no signature. |
| `r4683026-n303509`, w6 | 158/216 | One owner: 158/210 here against 332/1,645 elsewhere. The machine was almost theirs alone (others 0/6). |
| `r2215649-n410412`, w6 | 209/244 | One owner: 198/204 here against 292/1,651 elsewhere. Others 11/40. |

Each could be the machine, or particular work that was only ever sent there. The
data can't separate the two, which is exactly the burst detector's `undetermined`
reasoning. **The first one is the best candidate for a second silent fault.** Its
verdict stays `monitor`, but it is the first machine we'd inspect.

### Cross-check against the burst detector

Some flagged windows contain a `node-job-failure-burst`, whose 48-hour causal
attribution is independent of ours:

| Our cause \ burst attribution | hardware | user | undetermined |
|---|---|---|---|
| hardware | 1 | 0 | 0 |
| user_code | 0 | 12 | 10 |
| workload_mix | 0 | 1 | 2 |
| cannot_determine | 0 | 0 | 4 |

- **Where the burst detector named a cause, we agree in 13 of 14.** The exception
  (`r5179276-n772143` in window 8) is a burst one user dominated for 48 hours, inside
  a 14-day window where that user holds only 37% of the failures.
- **We go further in 10 of the burst detector's `undetermined` cases,** because our
  14-day window finds array siblings failing on other machines, which its 48-hour
  window doesn't see.

### Cost of being wrong

- **Calling user code hardware** drains a healthy machine (48 GPU-h a day) and
  leaves the owner's bug in place. That is why `hardware` requires a multi-owner
  signature: it fired once.
- **Calling hardware user code** leaves a broken machine in service. The mitigation
  is `monitor` on every `cannot_determine`, with the three above first in line.
- **Most of these 113 findings need no machine action at all.** 86 are about people
  or workload. That makes the finding count a poor drain signal, which leads into
  case 7.

---

## Case 7 — Auditing the API's recommendations

Script: `analysis/case7_drain_rec.py`

**Question.** `GET /v1/recommendations` offers *"Drain the top 5 underperforming
nodes… These nodes carry the highest finding counts in the fleet. Drain and submit
for hardware inspection."* It estimates **$57,226 (22,890 GPU-h)** saved, with
effort `low` and confidence 0.58. Should the CFO act on it?

**No.** It is the most expensive mistake on offer: none of the five machines shows
any evidence of a hardware fault.

### How the endpoint builds it (`api/main.py`, `api/data_loader.py`)

1. **Rank machines by the number of findings whose `resourceIds` include them.**
   `rootCauses` is never read.
2. **Take the top 5.** Three machines tie at 146 findings for 5th place
   (`r7317916-n303509`, `r5051220-n200569`, `r810901-n172107`), and the endpoint's
   dict order picks `r7317916-n303509`. **One of the five machines to drain is chosen
   by a tie-break.**
3. **"Savings" = the sum of their job-scope `impact_gpu_hours`**, which mixes `lost`,
   `consumed` and `unused_capacity` (docs: *don't add across kinds*). We reproduce
   22,890.

### What the five machines actually are

| Node | Findings | `array-task-failure` | Case 6 verdicts |
|---|---|---|---|
| `r4605940-n772143` | 259 | 209 | user_code (w4, w8) |
| `r7317916-n772143` | 165 | 134 | user_code (w4, w8) |
| `r3974592-n172107` | 164 | 122 | user_code (w0) |
| `r4144777-n172107` | 154 | 104 | user_code (w4); cannot_determine (w3, w7) |
| `r7317916-n303509` | 146 | 95 | user_code (w0); workload_mix (w1) |

- **Their finding counts come from arrays.** 664 of the findings on these machines
  (76% of all their findings carry a root cause elsewhere) resolve through
  `rootCauses` to a **Slurm array** (`k8s:job`). `POST /v1/causal` says those
  failures belong to the array, spread across many machines. The machines are
  crowded with symptoms of other people's broken scripts.
- **No hardware evidence.** None of the five has the multi-owner exit-status
  signature (case 5), and none has a node failure located on it (`nodefail_nodes`).
  Of their 10 flagged windows, 7 are `user_code`, 1 is `workload_mix` and 2 are
  `cannot_determine`. None is `hardware`.
- **The failures follow the people.** 1,078 FAILED jobs from 63 owners ran on these
  machines. Those owners fail 24.5% of the time on every other machine, against
  37.6% here, which is roughly what heavy array users produce wherever they land.
- **The machine that *was* broken ranks 21st.** `r216287-n200569`, the silent
  SIGBUS machine from case 5, has fewer findings than any of the five. A
  finding-count ranking doesn't find hardware faults.

### What following it would cost

- **Draining five 2-GPU machines** removes **1,680 GPU-h a week ($4,200)**, or
  21,840 GPU-h ($54,600) over a 13-week quarter.
- **Those machines were doing real work.** They delivered 15,300 card-hours over the
  window (51% of their capacity), 4,829 of them on jobs that completed.
- **The "savings" wouldn't happen.** The failing arrays would be rescheduled onto
  other machines and fail there, because the cause is in the scripts. At best,
  draining saves nothing. At worst, it removes capacity during a quarter when the
  CFO is trying to cut 20% "without slowing research down".
- **The right action for the same findings** is one conversation per failing
  array (case 2 and `rules::array-mass-failure`), plus the signature rule from
  case 5 for real hardware faults.

**The rival recommendation is also shaky.** `rec_lowutil` ("fractional-GPU queue",
$53,430) takes 35% of `gpu-low-utilization`'s 61,063 GPU-h. The 0.35 is a constant
in the code, not something the data supports. It cites only 20 of the 95 findings,
and 21 of those 95 jobs use 16 or more GPUs, which a fractional-GPU queue doesn't
serve.

### Argue with us: what Layer B should do instead

- **Group findings by `rootCauses` before ranking anything.** 121 volume findings
  and 5,044 array-task findings are two problems, not 5,165.
- **Rank machines on evidence that follows the machine** (a multi-owner signature,
  located node failures, excess failures after adjusting for each owner's own
  rate), not on how many findings touch them.
- **Break ties explicitly, or return all tied machines.** A drain list shouldn't
  depend on dict order.
- **Don't sum `impact_gpu_hours` across `impact_kind`,** and don't call the result a
  saving. Draining a machine recovers no GPU-hours; it removes them.

### Candidate CFO line

> The API's top suggestion, "drain five machines, save $57K", would cost $55K of
> capacity a quarter and save nothing: those machines are healthy, and the failures
> belong to a handful of broken scripts that would fail anywhere.

---

## Case 8 — The queue tail, and what waiting is worth

Script: `analysis/case8_queue.py`

**Question.** How long do researchers wait for GPUs, what is that worth, and would
a 20% capacity cut make it worse? The brief frames it as *"98,213 engineer-hours of
waiting… a salary number"*.

### Headline

**The API prices queue waiting at $9.33M, 6.3× the entire $1.49M GPU spend.**
Merged per person, the waiting comes to **4,997 person-hours**, and **3,719** of
those are past a 4-hour target. That is **$353K** at $95 an hour, *if* every waiting
hour blocked the person. People at a keyboard (interactive sessions) waited
**0.8 hours in total** over four months.

### Why $9.33M is wrong

`/v1/queue/latency` multiplies the sum of every job's `wait_sec` (98,214 h) by
$95. Three problems:

1. **It counts time jobs weren't eligible to run.** `wait_sec = time_start −
   time_submit` includes `time_eligible − time_submit`: **22,880 h (23%)** of held
   jobs, deferred start times and dependencies. All 30,713 such jobs are array
   tasks. Real queue time is `time_start − time_eligible`, **75,334 h**.
2. **It counts every job as a person.** 53% of jobs are array tasks. Someone with
   1,000 tasks pending waits once, not 1,000 times. Merging each person's
   overlapping waits turns 75,334 job-hours into **4,997 person-hours**.
3. **It treats waiting as staffed time.** The rule's own text says *"nobody sits
   watching a scheduler"*. The literal version, interactive sessions, is **$74**.

| Way to count | Hours | At $95/h |
|---|---|---|
| API: every job's full wait | 98,214 | $9,330,307 |
| queue time only, every job | 75,334 | $7,156,702 |
| queue time, merged per person | 4,997 | $474,730 |
| **past a 4 h target, merged per person** | **3,719** | **$353,319** |
| interactive sessions only | 0.8 | $74 |

We report **3,719 person-hours past target** (46 people, about 4.5 hours each per
week) and don't add it to the GPU savings. The $353K is an upper bound on salary
cost, because a researcher usually works on something else while a batch job waits.

### The shape: most jobs start at once, a few wait days

Queue wait (`time_start − time_eligible`), job-weighted: p50 **0 s**, p75 0.68 h,
p90 2.0 h, p95 4.6 h, **p99 14.8 h**, p99.9 53 h.

| Wait | Jobs | Share of jobs | Queue hours | Share of hours |
|---|---|---|---|---|
| < 1 min | 44,005 | 58.8% | 46 | 0.1% |
| 1–10 min | 5,612 | 7.5% | 383 | 0.5% |
| 10 min–1 h | 10,312 | 13.8% | 5,881 | 7.8% |
| 1–4 h | 10,728 | 14.3% | 19,655 | 26.1% |
| 4–12 h | 3,147 | 4.2% | 21,881 | 29.0% |
| 12–24 h | 746 | 1.0% | 12,456 | 16.5% |
| > 24 h | 288 | 0.4% | 15,031 | 20.0% |

**The slowest 1% of jobs (749) hold 31% of queue hours.**

- **By type:** batch and "other" jobs, arrays and non-arrays alike, hold nearly all
  of it. Interactive sessions have a p99 wait of 21 s.
- **By width:** single-GPU jobs hold 68,799 of the 75,334 h (median 12 s, p99
  15.7 h). The 398 jobs of 9 or more GPUs rarely wait (median 1 s), but their p99 is
  **192 h**: the widest jobs occasionally wait over a week for a contiguous block.
- **By requested time limit:** unlimited requests (31,778 jobs) hold 37,327 h, half
  of all queue time, with p90 3.7 h. Jobs asking for 4–24 h wait longest at the
  median (26 min). A scheduler can backfill only jobs whose limit fits a gap, so
  honest time limits are a free lever (see `rules::timelimit-overreservation`).

### The two queue findings don't say what they seem to

**`rules::queue-weekly-peak` is one day, not a weekly pattern.** Wednesday's 21,163
submissions include **14,134 from one owner (u-41415979807) on a single date,
2026-04-01**: 26 arrays of tasks running a median of 16 seconds each. They account
for **15% of all queue hours** and only 1,704 GPU-h of work. **Without that owner,
Wednesday's median wait is 1 second.** The finding averages a one-off burst into a
"weekday in seven". The fix is packing tiny tasks into fewer, longer jobs, not a
Wednesday capacity plan.

**`rules::queue-starvation`'s biggest "starved" user wasn't starved.** It reports
22,481 h for u-59477077536, but **22,291 h of that (99%) is pre-eligibility**:
jobs held by their own begin time or dependencies. Their real queue time is 189 h,
and only 8 of their jobs waited over 6 hours. Across all 22 starvation findings,
64,209 h = **22,608 h pre-eligible (35%)** + 41,600 h queue. The rule should use
`time_eligible`, not `time_submit`.

**`rules::queue-wait-p95-slo`**: we reproduce the breach weeks (p95 over 4 h,
100+ jobs) under any week grouping. Depending on whether jobs are grouped by
submit, eligible or start time, we find 1 or 2 more weeks (2026-03-11, 2026-06-10)
than the 8 findings; the rule's exact week boundary isn't documented. **Every
breach has a median wait of 0.00–0.03 h: these are tail problems, not a slow
queue.** The worst, the week of 2026-06-03 (p95 23.6 h), is one burst.

### Is capacity what makes people wait?

We built a 10-minute timeline of GPUs held by the sample's jobs (capacity 450):

- **GPUs held:** median 191, p95 312, max 404.
- **Someone had waited more than an hour and was still pending 78% of the time.**
  GPUs held then: median 201, against 160 otherwise.
- **Correlation between GPUs held when a long-waiting job became eligible and its
  wait: 0.15.** The long waits barely track how full this sample is. They track
  bursts, fairshare and per-user limits, and load outside the sample.
- **While someone was waiting, jobs that never ran a kernel held a median of 34
  GPUs:** 80,367 GPU-h ($201K) of idle allocation during contention. **In 62% of
  those moments, the idle-held GPUs outnumbered the GPUs the long-waiters were asking
  for.**

**Caveat: the data is a sample.** MIT says it isn't fit for estimating utilization,
and other jobs that aren't in the sample share these machines. "GPUs held" is a
lower bound, so read the timeline as a shape, not a measured level.

### Cost of being wrong about a 20% cut

- **The fear:** cutting capacity 20% (to 360 of 450 GPUs) lengthens the queue tail
  and slows research, which the CFO was told not to do.
- **What the sample shows:** it holds more than 360 GPUs **0.6%** of the time.
  Without the never-ran jobs (case 2), it **never** does. So the idle-kill and
  placement cuts free the same GPUs a cut would remove, and they come out of the
  hours when people are waiting.
- **Order matters:** reclaim idle allocations first (case 2), then cut capacity.
  A cut without reclaiming idle GPUs pushes contention onto the 1% tail, whose
  wait is already 15 hours.
- **Because the sample understates load,** watch the p95 queue SLO weekly after
  any cut, and treat a new breach week as the signal to stop.

### Candidate CFO line

> Researchers rarely wait: most jobs start instantly. The painful tail, 3,700
> person-hours past a 4-hour target, comes from bursts, not a full cluster, and
> idle-but-allocated GPUs could have served most of it. Reclaim those first and a
> 20% cut shouldn't slow anyone down. The API's "$9.3M of waiting" counts one
> person with 14,000 tiny tasks as 14,000 people.

---

## Case 9 — Is the scheduler optimized, and would reordering cut the cost?

Script: `analysis/case9_scheduler.py`. Output: `analysis/out_case9_scheduler.csv`.

**Question.** The API prices queue waiting at $9.33M. Is the scheduler doing a bad
job, and would reordering the queue recover any of it?

**Answer: no, and no.** The scheduler is close to optimal for the order it is given.
The waiting is caused by **per-user concurrency caps binding while the cluster is
two-thirds empty**. Reordering cannot fix that; raising the caps and killing idle
allocations can.

### First: the scheduler is already doing the right things

- **It is FIFO.** Rank correlation between eligible order and start order is
  **0.9966**.
- **Backfill works.** Small jobs are not stuck behind big ones: median wait is
  12 s for 1-GPU jobs, 1 s for 2-GPU, 1 s for 3-8 GPU jobs. In simulation,
  removing backfill makes waiting **26% worse** and quadruples the jobs that
  breach 4 hours (6 → 17).
- **Nothing suggests a misconfigured priority.** `priority` correlates with wait
  at **-0.019**, `gpu_count` at 0.024, `dur` at 0.079. No dimension of the job
  predicts its wait, which is what you expect when a quota, not the queue, is the
  constraint.

### Then: replaying the stream under other policies

A discrete-event simulator at 450 GPUs, fed the real eligible times, GPU counts and
runtimes, with a 400-job backfill window. Person-hours merge each owner's
overlapping waits, as in case 8.

| Policy | Total wait (h) | p95 | p99 | Jobs > 4 h | Person-hours |
|---|---|---|---|---|---|
| **OBSERVED (real)** | **75,334** | 4.64 h | 14.82 h | 4,181 | 23,212 |
| FCFS, no backfill | 4,484 | 0.19 h | 1.24 h | 17 | 85 |
| **FCFS + backfill** (≈ the real scheduler) | 4,099 | 0.19 h | 1.18 h | 6 | 67 |
| SJF (oracle runtime) | 3,307 | 0.16 h | 0.93 h | 1 | 52 |
| Smallest-first (GPUs) | 4,012 | 0.19 h | 1.15 h | 1 | 62 |
| Fair-share round robin | 3,967 | 0.19 h | 1.18 h | 1 | 47 |
| FCFS + 1 h idle-kill | 3,031 | 0.18 h | 0.79 h | 0 | 24 |
| **SJF + 1 h idle-kill** | **2,607** | 0.14 h | 0.70 h | 0 | 20 |

Relative to the FCFS-with-backfill baseline: SJF **-22%** person-hours, fair-share
round robin **-30%**, smallest-first **-7%**, and the **idle timeout -64%** on its
own — **-70%** combined with SJF.

**Two caveats that matter more than the ranking.**

1. **The simulator's absolute waits are ~18× below the observed ones** (4,099 h
   against 75,334 h). These jobs cannot fill 450 GPUs; the sample excludes the rest
   of the cluster's work. So the table shows *ordering effects*, never savings.
2. **SJF is given each job's true runtime**, which no scheduler knows in advance. It
   would have to use the requested limit, and **42% of these jobs request no limit
   at all**. SJF here is an upper bound on what reordering could ever buy.

**Even at face value, reordering is worth tens of person-hours in this sample, not
millions of dollars.** The $9.33M is a pricing artefact (case 8), not a scheduler
bug.

### The real cause: per-user caps, not capacity or order

Sampling 1,200 jobs that waited more than an hour, and asking what was running at
the moment each became eligible:

| At the moment a job began waiting > 1 h | Median | 90th pct |
|---|---|---|
| GPUs the **same user** already held | **16** | 50 |
| Jobs the same user already had running | 16 | 50 |
| GPUs held **cluster-wide** (of 450) | 163 | 312 |

- **90% of long waits happen while that user already holds 10+ GPUs.**
- **The cluster was never above 380 of 450**, and above 300 only 16% of the time.
- **Median free capacity when someone waited over an hour: 287 of 450 GPUs (64%
  idle).**
- The per-user numbers are **quantized**: among the 93 users with 50+ jobs, peak
  concurrency clusters at **16 / 17** (28 users), **32** (9 users) and a few at
  **65-66**. Those are quota ceilings, not coincidences. The eight users who did
  most of the waiting all sit at 31, 32, 65 or 66.

**So the queue is not full — the users are capped.** A researcher submits 200 array
tasks, 16 run, and the other 184 wait for their own jobs to finish while hundreds
of cards sit free.

### What would actually cut the waiting

1. **Make the per-user cap elastic.** Let a user exceed their cap when the cluster
   is below, say, 70% allocated, with those jobs marked preemptible so the quota
   still holds when demand returns. This targets the 90% of long waits that are
   self-inflicted queueing, and it costs no capacity: the cards are already idle.
2. **The idle timeout from tile 2 — the same action, twice paid.** It returns
   $205K of GPU time *and* is the single biggest queue improvement in simulation
   (-64% person-hours), because an idle job holds both a card and a slot against
   its owner's quota. Killing it frees the owner's own queue.
3. **Reserve for wide jobs, but expect little.** Only **13 jobs** waited more than
   24 hours; all were 16-GPU jobs from **2 owners**, and the cluster held a median
   of 264 of 450 GPUs when they began waiting — so even these were not capacity, and
   the 9+ GPU p99 of 192 hours is 13 jobs, not a class of work.
4. **Ask people for honest time limits.** Jobs requesting no limit hold half of all
   queue time. Backfill can only place a job whose limit fits the gap, so an honest
   limit is free throughput — and `rules::timelimit-overreservation` already
   identifies the 41 worst offenders.

### Caveat on the free-capacity figure

"287 of 450 free" counts only jobs in this sample. The real machine also ran
CPU-only and non-sampled work, so true free capacity was lower. **The cap evidence
does not depend on it**: the quantization at 16 / 32 / 65 is visible in the users'
own concurrency, whatever else the cluster was doing.

### Candidate CFO line

> Researchers are not waiting for hardware. They are waiting for their own quota:
> in 90% of long waits the person was already at their cap while ~287 of 450 GPUs
> sat free. Reordering the queue buys nothing; relaxing the cap when the cluster is
> quiet, and reclaiming idle allocations, removes almost all of it.

---

## Case 9b — The scheduler simulated properly: now vs optimized

Script: `analysis/case9b_caps.py`. Outputs: `analysis/out_case9b_caps.csv`,
`analysis/out_case9b_sweep.csv`.

**Question.** Case 9's replay produced waits far below the real ones. Run it over
every job with the missing constraint — the per-user cap — and measure what the
optimizations are worth.

### Scope: this is every job, and here is what is still missing

**All 74,838 jobs with a start time are simulated** (the dataset has 74,849; the
other 11 never started, so they have no observed wait to compare against). Nothing
is sampled down.

What cannot be added is the rest of the machine's work: MIT published this dataset
as a **sample** of the cluster's jobs, and the unsampled jobs are not in the files.
So instead of claiming a full-fidelity replay, the cap model is **validated against
the observed wait distribution** and reported with its error.

### Where the caps come from

Each user's cap is their **observed peak simultaneous GPUs**, swept from their real
start and end times, then snapped onto the `16 / 32 / 64` ladder when it lands
within 10% of a rung (18 of 195 users snap; the median cap is 8 GPUs, because most
users never ran much at once).

This is an estimate, and it is endogenous: a user's peak is what they *achieved*,
which for a light user reflects their own submissions rather than a ceiling. It is
right where it matters — the heavy users who do the waiting pile up exactly on the
rungs (28 users at 16-17, 9 at 32, a few at 65-66).

### The model against reality

| | Observed | Model with caps | Model without caps (case 9) |
|---|---|---|---|
| total wait | **75,334 h** | **30,245 h** | 4,099 h |
| person-hours | **4,997** | **1,326** | 67 |
| p50 | 7 s | 0 s | 0 s |
| p90 | 2.03 h | 0.99 h | — |
| p95 | 4.64 h | 1.73 h | 0.19 h |
| p99 | 14.82 h | 5.35 h | 1.18 h |
| jobs over 4 h | 4,181 | 1,040 | 6 |

**Adding the cap takes the model from 1.3% of the observed waiting to 40% of it**
(person-hours 67 → 1,326 against 4,997). That is the single biggest missing
constraint, and it is strong evidence the caps — not capacity, not ordering — are
what people are waiting for.

**The remaining 60% is what we cannot see:** the unsampled jobs that also competed
for these cards, plus fairshare decay, QOS limits and reservations that Slurm
applies and this data does not record. So the model **understates** every saving
below; it does not overstate them.

### Now vs optimized

| Policy | Total wait | p95 | p99 | Jobs > 4 h | Person-hours | Δ vs now |
|---|---|---|---|---|---|---|
| **NOW: caps as they are** | 30,245 h | 1.73 h | 5.35 h | 1,040 | **1,326** | — |
| OPT 1: 1 h idle timeout | 29,156 h | 1.70 h | 5.13 h | 988 | 1,192 | **-10%** |
| OPT 2: elastic cap under 70% | 9,553 h | 0.30 h | 2.55 h | 378 | 168 | **-87%** |
| **OPT 3: both** | **8,046 h** | 0.28 h | 2.21 h | 305 | **59** | **-96%** |
| OPT 4: both + shortest-job-first | 6,554 h | 0.24 h | 1.92 h | 169 | 49 | -96% |
| *REF: double every cap* | 10,516 h | 0.66 h | 1.76 h | 97 | 132 | -90% |
| *REF: remove caps entirely* | 4,099 h | 0.19 h | 1.18 h | 6 | 67 | -95% |

**The elastic cap is the whole story.** Letting a user exceed their quota while the
cluster is below 70% allocated removes **87%** of the modelled waiting on its own;
with the idle timeout it removes **96%**. Reordering (OPT 4) adds almost nothing
once the cap is elastic — the same conclusion as case 9, now measured under a model
that reproduces 40% of reality instead of 1%.

**Hours are the honest unit.** OPT 3 returns **1,267 person-hours**. Priced at the
price book's $95 an engineer-hour that is **up to $120,000**, but the conversion
assumes the wait fully blocks the person — the same assumption we argue against in
`/v1/queue/latency` (case 8), where the rule catalogue's own text says *"nobody sits
watching a scheduler"*. A researcher waiting on a batch job usually works on
something else, and nothing here measures how much. **We do not add it to the $359K
of GPU savings**: that is cash you stop spending, this is throughput you get back. Scaled to the full observed waiting it would be larger, but that
scaling is not something this data can verify, so the defensible claim is: *at
least 1,267 person-hours of researcher time — up to $120K if that waiting fully
blocks the person — and the model understates it.*

**Reference rows are the sanity check.** Doubling every cap (-90%) and removing
caps entirely (-95%) both land near the elastic result, which confirms the
mechanism: the ceiling is what binds, and the elastic rule buys nearly all of the
benefit of removing it while keeping the quota for the hours when the cluster is
actually busy.

### Where to set the threshold

**This is interactive on the dashboard** (tile 4, "Try the fix"): a slider over the
threshold and a toggle for the idle timeout, backed by a 12-run grid — every
setting is a full replay of all 74,838 startable jobs, precomputed when the page
builds, so the slider selects between real simulations rather than interpolating.

With the idle timeout on:

| Let users exceed their cap below… | Person-hours | Jobs > 4 h | p99 |
|---|---|---|---|
| 50% allocated | 372 | 480 | 3.04 h |
| 60% | 193 | 376 | 2.58 h |
| **70%** | **59** | **305** | **2.21 h** |
| 80% | 29 | 203 | 1.63 h |
| 90% | 18 | 0 | 1.22 h |

The curve is smooth up to 80%, so this is a dial rather than a cliff — but it is
not monotonic at the top. Without the idle timeout, 80% gives 59 person-hours and
90% gives 68: past a point, more jobs start early and then compete with each other.
**70% is the conservative choice** — it keeps 30% of the cluster's capacity governed by quota
for the busy hours, and still removes 96% of the modelled waiting. Going to 90%
removes almost all of it but leaves the quota with nothing to do, which is a policy
decision about fairness rather than a technical one.

### Cost of being wrong

- **The caps exist for a reason.** They stop one researcher taking the cluster
  during a busy week. The elastic rule only lifts them while the machine is quiet,
  and the extra jobs should be **preemptible** so the quota reasserts itself the
  moment demand returns. We simulated them as ordinary jobs, which is the
  optimistic case: with preemption, some of that work would be interrupted and
  resubmitted.
- **Our caps are inferred, not read from Slurm.** If the real ceilings differ, the
  size of the effect changes but not its direction: the reference rows show any
  loosening of the ceiling lands in the same place.
- **The model understates waiting by 60%**, so it also understates the gain.
- **This buys researcher time, not GPU-hours.** It does not contribute to the 20%
  spend cut; it is what makes the cut safe to take, which is the question the CFO
  was actually asked.

### Candidate CFO line

> Modelling every job with the real quotas in place, 96% of the waiting comes from
> researchers hitting their own cap while the cluster is two-thirds idle. Lifting
> the cap only while the machine is quiet, plus the idle timeout, removes it —
> 1,267 person-hours handed back to researchers, and it costs no capacity. (Worth up
> to $120K if that waiting fully blocks them; we report the hours, because that
> conversion is the one we argue against in `/v1/queue/latency`.)

---

## Case 10 — Predicted quotas and a credits pool: are they credible?

Script: `analysis/case10_credits.py`. Outputs: `analysis/out_case10_policies.csv`,
`analysis/out_case10_loan_sweep.csv`, `analysis/out_case10_full.log`.

**Question.** The elastic quota of case 9b is reactive: it lifts the cap whenever
the cluster is quiet, with no idea who is about to come back, and without
preemption a long job started in a quiet hour still holds its cards when everyone
returns. Two alternatives were proposed: **forecast each researcher's quota**, and
a **credits pool** where someone who is away lends their unused quota for a bounded
window. Are they credible?

### The objection to the elastic rule is right, and the sample cannot test it

In this sample the elastic rule harms almost nobody: 57 researchers better off, 2
worse, by 0.2 hours at most. **But that is because the sample is rarely full.** The
mechanism of harm is visible anyway: of the 21,570 jobs that start earlier under the
elastic rule, **136 run longer than 24 hours and one for 8 days**. Those are the jobs
that would hold cards when demand returns. The −87% in case 9b is therefore an
upper bound under conditions that flatter it.

### Results (all 74,838 startable jobs, 18 weeks)

| Policy | Person-hours | vs today | Jobs > 4 h | Borrowed | Harm to lenders |
|---|---|---|---|---|---|
| **Today: fixed quotas** | **1,326** | — | 1,040 | — | — |
| Elastic quota under 70% | 168 | −87% | 378 | — | *untestable here* |
| Predicted quota (2-week demand history) | 18,767 | **+1,316%** | 25,671 | — | — |
| Pool, gated on **requested** time limit | 1,326 | 0% | 1,040 | 26 GPU-h | 0 h |
| **Pool, gated on predicted runtime** | **1,183** | **−11%** | 938 | 10,028 GPU-h | 4.3 h |
| **Pool (predicted) + 1 h idle timeout** | **1,047** | **−21%** | 894 | 9,748 GPU-h | 0 h |
| *Reference: no quotas* | 67 | −95% | 6 | — | — |

### Idea 1 — forecasting each researcher's quota: not credible on this data

The forecast sizes next week's quota from the researcher's **peak in-flight demand
over the previous two weeks**, strictly causal, clipped to 2–64 GPUs.

**Demand is too bursty to forecast.** Across active researcher-weeks (six-week
check): the forecast was **too low 21% of the time**, and when it was low the
researcher needed a median **2× the forecast**; **13% of active weeks followed two
weeks of no demand at all**. Someone submits a 500-task array out of nowhere, meets
a quota sized for their quiet fortnight, and queues behind themselves. Waiting rises
**1,316%** and 133 of 195 researchers are worse off.

Two honest caveats. Today's quotas were inferred from each researcher's peak over
the whole four months, so the baseline has **hindsight** the forecast does not. And
a too-tight quota only hurts in a sample with spare capacity; on a saturated
cluster, tighter quotas buy fairness this data cannot show. What survives both
caveats: the forecast's *direction* is informative — median demand (16 GPUs) is
double the median quota (8), and the forecast is tighter than today's quota in 34%
of researcher-weeks — so today's ladder is misallocated. **Use the forecast to
review quotas quarterly, not to set them weekly.**

(An earlier version of this forecast took a time-weighted 95th percentile of
demand. That is dominated by the hours a researcher has nothing in flight and
collapsed every quota to 1 GPU. A quota has to cover the peak.)

### Idea 2 — the credits pool: credible, once the gate is right

**Design.** A researcher who has been away — nothing running, nothing queued, for 4
hours — makes their quota available to a pool. **Their own quota is never reduced**,
so nobody is blocked by their own generosity. A waiting job may run over its owner's
quota only if it is expected to finish inside the **loan window**, and nobody may
borrow more than their own quota again. The cost of lending lands on the *cluster*,
and the harm we measure is exactly that: researcher-hours spent queued, under their
own quota, because the cluster was full while borrowed jobs were running.

**Gating on the requested time limit makes the pool inert.** The median requested
limit is 24 hours; the median runtime is about a minute: a **2,057× over-ask**. At
the mean-job-length window only a handful of jobs qualify, and 26 GPU-hours were
ever borrowed.

**Gating on predicted runtime makes it work.** A job's runtime *is* predictable from
its owner's history: the p90 duration of their jobs that had finished before this
one became eligible (causal). 98% of jobs have a usable history, and 85% finish
within the prediction.

**The loan window is the mean job length (5.11 h)** — long enough that 43% of jobs
are predicted to fit, short enough that a loan is back within a working session.
The median job is 2 minutes; the mean is pulled up by a long tail.

| Loan window | Person-hours | vs today | Borrowed GPU-h | Ran past the window | Harm |
|---|---|---|---|---|---|
| 1 h | 1,284 | −3% | 4,525 | 2,933 | 4.0 h |
| 2 h | 1,267 | −4% | 7,453 | 2,923 | 4.0 h |
| **5.11 h (mean job)** | **1,183** | **−11%** | 10,028 | 2,626 | 4.3 h |
| 12 h | 1,092 | −18% | 15,345 | 2,670 | 4.4 h |
| 24 h | 995 | −25% | 23,183 | 1,213 | 4.3 h |

**The lender's risk, measured: 4.3 researcher-hours** across 18 weeks, against 1,577
saved. 28 researchers better off, 6 worse, the worst by 20 hours. The harm barely
moves with the window, because it is bounded by design rather than by luck.

**This is interactive on the dashboard** (tab 4): a loan-window slider, a toggle
between gating on predicted runtime and on the requested limit, and the idle-timeout
checkbox. It reads a 17-run grid from `analysis/case10_grid.py`, which replays all
74,838 jobs per setting in parallel. Each pool replay takes about 45 seconds, so
unlike the quota dial the grid is precomputed and committed
(`analysis/out_case10_grid.json`, policy-level aggregates only) rather than run at
container start.

### The pool's honest weakness

**26% of borrowed GPU-hours ran past the loan window.** By *count* only about 7.5%
of borrowing jobs overrun, but the rare long ones carry the hours. A production pool
needs a backstop: borrowed jobs become **preemptible once past the window**, or the
gate uses a stricter percentile than p90. We did not simulate preemption, so the
figures above are the pool *without* that protection.

### Verdict

| Idea | Credible? | Why |
|---|---|---|
| Forecast quotas weekly from recent demand | **No** | Demand is bursty; 21% under-forecast by 2×; waiting +1,316% |
| Use the forecast to review quotas quarterly | Yes | Median demand is 2× median quota; 34% of researcher-weeks over-provisioned |
| Credits pool, gated on requested limits | **No** | Limits over-asked 2,057×; the pool never lends |
| **Credits pool, gated on predicted runtime, window = mean job length** | **Yes** | −11% (−21% with the idle timeout), harm 4.3 h, risk bounded by design |
| Elastic quota | Only with preemption | −87% here, but reactive, and this sample cannot test the return-to-busy case |

**Recommended order:** the 1 h idle timeout, then the credits pool, and the elastic
rule only once preemption exists. The pool is weaker than the elastic rule in this
sample, and that comparison flatters the elastic rule for the reason the objection
gives: a bounded loan is safe under load in a way "lift the cap while quiet" is not.

**Same caveats as case 9b:** quotas are inferred, the model reproduces 27% of
observed person-hours, and the sample understates both the benefit *and* the
lender's risk.
