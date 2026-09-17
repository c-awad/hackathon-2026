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
| 2b | Which GPU jobs could run on CPU instead | done |
| 3 | Card imbalance | done |
| 4 | The shared-storage incident | done |
| 5 | Hardware-attributable failures | done |
| 6 | Node triage (113 elevated-failure-rate findings) | next |
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
