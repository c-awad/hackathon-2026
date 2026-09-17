# Track 2 — Where to cut $1.49M of GPU spend, and what not to touch

**The dashboard is the deliverable.** `docker compose up`, then
**http://localhost:3000**. This report is the argument behind it.

- [`ANALYSIS.md`](track-2/ANALYSIS.md) — the working, case by case (1 to 9b)
- [`API_ANALYSIS.md`](track-2/API_ANALYSIS.md) — every MantisGrid endpoint reviewed, and
  three bugs
- [`claims.json`](claims.json) — the numbers, machine-readable
- `track-2/analysis/` — a script per case; every figure in this report is reproducible

---

## The answer in five lines

| | |
|---|---|
| **Spent** | $1.49M (594,004 GPU-hours, 4 months, 225 machines) |
| **Recoverable** | **$359K** (range $202K–$491K), 24% of capacity |
| **The 20% target** | $297K — the point estimate clears it, the low end does not |
| **Machines to drain** | **one** (not the 121 the findings suggest, not the 5 the API recommends) |
| **Queue** | a quota problem, not a capacity one; fixable for **1,267 person-hours** (up to $120K if fully blocking) at no capacity cost |

**The one-line version for the CFO:** *most of the recoverable money is GPUs nobody
was using — not machines to switch off and not people to chase.*

---

## 1. Where the money went

Only **17%** of what was paid for was both busy *and* on a job that finished. That
is the brief's "83% did not turn into completed work", and it is **not** the same as
83% being recoverable.

| Outcome | GPU-h | $ | Of it, busy |
|---|---|---|---|
| Completed | 229,041 | $572,601 | 100,789 |
| Cancelled | 203,930 | $509,824 | 69,956 |
| Timed out | 107,952 | $269,879 | 43,717 |
| Failed | 50,033 | $125,083 | 14,354 |
| Node failure + undecoded | 3,049 | $7,623 | 89 |

**A quarter of all spend sat at 0% average utilisation.** Tightening that to jobs
whose average **and** peak were zero — GPUs that never ran a single kernel — gives
**97,196 GPU-hours, $243K**. That is the cleanest waste pool in the data, because no
reading of "useful work" covers a card that computed nothing.

**What we refused to count.** 40,710 GPU-hours of timed-out jobs ran at 80–100%
utilisation: real work destroyed at the wall clock, where the remedy is
checkpointing, not a cut. And cancelled jobs ran at 34.3% against the cluster's
38.5%, so we count only the idle time *before* a cancel (`cancelled_is_waste:
false`). Counting all of CANCELLED would roughly double the headline by promising
work that was already useful.

## 2. Where to cut

Each job lands in exactly one class, so no GPU-hour is counted twice. The hours come
from `jobs.parquet`, not from the findings — summing the detectors' own
`impact_gpu_hours` claims **157% of the cluster**.

| Action | $ | Range | Owner | Confidence |
|---|---|---|---|---|
| **End allocations sitting at zero** (1 h idle timeout) | **$205K** | $166K–$212K | Scheduler policy | 0.85 |
| **Send CPU work to CPU nodes** | $79K | $31K–$83K | Launcher defaults + 10 owners | 0.7 |
| **Right-size 2-GPU jobs using one card** | $36K | $29K–$48K | 10 owners (85% of it) | 0.6 |

**The idle timeout barely depends on its grace period**, which is why we lead with
it: these jobs sat idle for days (hour-weighted median wall time 96 hours). A
1-hour grace returns $205K; an 8-hour grace nobody could call aggressive still
returns $166K.

**Two thirds of map-reduce GPU time never opened the GPU at all** — no kernel, no
GPU memory allocated, idle power draw (median 25.8 W). That is a placement default,
not a workload problem, and 98% of those jobs' requests fit a 40-core/384 GiB node.

**Card imbalance is invisible in the table most dashboards read.** `jobs.parquet`
averages a job's cards, so one card at 0% and one at 65% reads as an ordinary 33%
job. From `gpus.parquet` at one row per card, 13,700 GPU-hours sit on cards that a
job held and never drove.

## 3. What it costs if we are wrong

The tile we care about most, and three of its four entries are things the API or its
numbers actively suggest.

| The mistake | Suggested by | Claimed | What it actually costs |
|---|---|---|---|
| **Drain the 5 machines with the most findings** | `GET /v1/recommendations` | $57,226 saved | **$55K/quarter of capacity, saves nothing** |
| **Drain the 121 machines in the storage incident** | 121 findings | $21,635 | **$29K, 54% of the cluster offline for 48 h** |
| **Count every cancelled job as waste** | `GET /v1/waste/breakdown` | $509,825 | **$292K of work that was already useful** |
| **Price queue waiting as salary** | `GET /v1/queue/latency` | $9,330,307 | a number 6.3× the GPU bill, not capacity |

**The drain recommendation is the expensive one, and the API refutes it itself.** It
ranks machines by how many findings touch them and never reads `rootCauses`. Passing
its 20 cited findings to `POST /v1/causal`: **15 have no root cause at all**. The
array-task findings on those same machines resolve to their **Slurm array at score
1.0**, with each machine at its thin share of the failures (0.05–0.4). One broken
submission script, not five broken machines. Our own triage of those five machines
(case 6) finds no hardware on any of them. The machine that really did break ranks
**21st** by finding count.

**The storage incident is one volume.** All 121 findings resolve to
`pvc/scratch-lustre-02` at 0.88 with the machines at 0.31, and every flagged machine
mounts it. `incident_nodes_to_drain: 0` — one ticket to the storage team. Draining
would take 54% of the cluster offline and every machine would come back to the same
slow volume.

## 4. The machine we *would* drain

**One**, and the scheduler never noticed it.

`r216287-n200569` failed **140 of the 144 jobs** it ran between 2026-02-27 and
03-07. We found it with a test that does not rely on the scheduler: for every
(machine, exit status) pair, count owners who crashed there 3+ times with that
status and **never** produced it anywhere else. Across all 225 machines, exactly one
pair passes — **SIGBUS (status 135), three unrelated owners**, 86 + 23 + 5 crashes
against **zero** in their 946, 1,427 and 1,544 jobs on other machines.

- **It could have been caught six days earlier.** A second, unrelated owner hit the
  same crash on 03-01 at 19:16; **36 more jobs crashed** before the finding was
  raised on 03-07. Draining then would have cost about **$700** of capacity.
- **Ranking by finding count would never find it** (21st), and neither would
  filtering on `state_name == NODE_FAIL` (it has none).
- **`hardware_attributable_failures: 145`** — 0.8% of the 18,587 failures. Almost
  everything else is user code. Attributing every failure to infrastructure would
  overstate what fixing hardware recovers by **more than 100×**.

## 5. Why machines look bad when they are not

`rules::node-elevated-failure-rate` fires **113 times across 87 machines** and
reports a symptom with no cause. We triaged every one, reproducing the rule's own
counts first (112 of 113 match exactly; the odd one is short by a single non-failed
job).

| Cause | Findings | What we would do |
|---|---|---|
| `user_code` | 46 | nothing to the machine — talk to the owner |
| `workload_mix` | 40 | nothing |
| `cannot_determine` | **26** | monitor |
| `hardware` | **1** | act (the SIGBUS machine) |

Each test compares **like with like**, which is the whole difficulty: "whoever owns
most failures" is not a test, and "does this person fail elsewhere" is not one
either unless the work is comparable. The strongest evidence is a Slurm array's
identical tasks failing on other machines too.

**`cannot_determine` on 26 of them is a result, not a gap.** One is worth a look:
`r7317916-n172107` in window 7, where 193 of 234 jobs failed, four owners failed at
2×+ their own rate elsewhere, and the top owner went 55/55 there against 6/177
elsewhere while their array siblings on other machines succeeded 11/11. Every
failure used the generic exit status 1, so there is no signature — it stays
`monitor`, but it is the first machine we would inspect.

## 6. Would cutting 20% make researchers wait?

**No — because they are not waiting for hardware.** They are waiting for their own
quota.

We replayed **all 74,838 startable jobs** at 450 GPUs (`analysis/sched_sim.py`, run
live when the dashboard builds).

| | Observed | Model with quotas | Model without |
|---|---|---|---|
| total waiting | 75,334 h | 30,245 h | 4,099 h |
| person-hours | 4,997 | 1,326 | 67 |
| p99 wait | 14.82 h | 5.35 h | 1.18 h |

**Adding each researcher's concurrency quota takes the model from 1% of the observed
person-hours to 27%** (40% of total waiting). That jump is the finding: the quota is
the binding constraint. In **90%** of waits over an hour, the person was already at
their cap while a median of **287 of 450 GPUs sat free**, and peak per-user
concurrency is quantised on a **16 / 32 / 64** ladder.

| Policy | Person-hours | vs today |
|---|---|---|
| Today's quotas | 1,326 | — |
| 1 h idle timeout | 1,192 | −10% |
| Elastic quota below 70% allocation | 168 | −87% |
| **Both** | **59** | **−96%** |
| Both + shortest-job-first | 49 | −96% |

**The fix is interactive on the dashboard.** Tile 4 carries a slider for the
threshold and a toggle for the idle timeout, backed by 12 precomputed full replays,
so a viewer can move the dial and watch person-hours, jobs over 4 hours, p95, p99
and the dollar value move with it — and see where the curve stops improving (above
80% it flattens and slightly reverses, because more jobs start early and compete).

**We report this in hours, not dollars.** The $95/engineer-hour conversion assumes
waiting fully blocks the person, which is the assumption we argue against in
`/v1/queue/latency`; the dashboard shows the dollar figure as an upper bound beside
the hours and never adds it to the $359K of GPU savings. Salary is a different
budget from hardware, and throughput regained is not cash saved.

**Reordering the queue buys nothing.** The scheduler is already near-FIFO
(correlation 0.997) with working backfill — removing backfill makes waiting 26%
worse. The fix is the quota, and the idle timeout pays twice: it returns GPU money
*and* frees the slot an idle job holds against its owner's quota.

**A safer alternative to the elastic quota (case 10).** The elastic rule is
reactive: it cannot know who is about to come back, and 136 of the jobs it starts
early run longer than a day. We tested two proposals against it. *Forecasting each
researcher's quota from their recent demand* fails — demand is too bursty, the
forecast is 2× too low in 21% of active weeks, and waiting rises 1,316%. *A credits
pool* — a researcher who is away lends unused quota for a bounded window — works
once it is gated on **predicted runtime** (the owner's historical p90) rather than
on requested limits, which are over-asked 2,057×: waiting falls **11%, or 21% with
the idle timeout**, and lenders were blocked for just **4.3 researcher-hours** in 18
weeks. It is weaker than the elastic rule here but its risk is bounded by design,
so our order is: idle timeout, then the pool, and the elastic rule only with
preemption.

**So the order of operations matters:** reclaim idle allocations first, then cut
capacity. This sample holds more than 360 of 450 GPUs only 0.6% of the time, and
never once the never-used allocations are returned. Watch the weekly p95 queue SLO
after any cut and treat a new breach week as the signal to stop.

## 7. What we checked and ruled out

- **Data movement is not the bottleneck.** `rules::gpu-pcie-saturated` is armed and
  has never fired: peak PCIe is 4,240 MB/s of a 15,754 MB/s link (27%). "Fix the
  data pipeline" never reached our list, and a rule that found nothing is why.
- **Wide jobs are not the problem.** Hour-weighted, utilisation *rises* with width
  (29% at 1 GPU to 59% at 9+). Counted by jobs it looks the opposite way. Only the
  hour-weighted view is about money. (On finer bands it is not monotonic — the
  17–64 band falls back to 32%, which is the one worth asking about.)
- **Severity is not cost.** The 31 `CRITICAL` job-scope findings carry $19K of
  impact; the 8,254 `LOW` ones carry **$759K**. Sorting findings by severity is one
  query away and would point a CFO at the wrong 2%.

## 8. Where our numbers could be wrong

- **SM utilisation is a proxy for useful work.** A data-loader-bound or
  communication-bound job does real work at low occupancy. This is the single
  largest source of error in the recoverable figure, and it is why the idle timeout
  targets a **peak** of exactly zero rather than a low average.
- **The near-idle class is the risky half.** 2,564 jobs (43,217 GPU-h) average under
  5% but peak above 50%. A policy keyed on average utilisation would kill real
  bursty work, so we count only half of that class and only in the point estimate.
- **The scheduler quotas are inferred**, from each owner's observed peak
  concurrency, not read from Slurm. The reference runs (double every quota: −90%;
  no quotas: −95%) show the direction holds even if the values move.
- **The queue model understates.** It reproduces 27% of observed person-hours; the
  rest is work outside this sample, so the 1,267 person-hours is a floor.
- **This is a sample.** MIT publishes it as a four-month sample of the cluster's
  jobs and says it is not appropriate for estimating system utilisation. Every
  figure here describes the sample. The storage incident is the corpus's one
  synthetic scenario; everything else is computed from real telemetry.
- **Owners stay hashed.** These views identify where recoverable capacity is, not
  who to blame. `GET /v1/resources/underperforming?entity_type=user` ranks people;
  we reviewed it and deliberately kept it off the dashboard.

## 9. What we built on the API, and what we would change

Nine of the twelve endpoints feed the dashboard; the other three we reviewed and
rejected for stated reasons. `POST /v1/causal` runs **live on the page** — tile 3
shows its answer next to the recommendation it contradicts. We also drove the MCP
server (`make mcp-demo`, transcript in `analysis/out_mcp_transcript.md`), which is
where the rule *"never act on a judgment without passing it through `causal`"*
belongs: in the tooling, not in our heads.

**Three bugs, with locations:**

1. **`POST /v1/neighbor` truncates silently.** `api/main.py:142` caps the node set
   at 500, and the cap is applied *before* edges are gathered — so `hop_count: 2`
   returns 500 nodes and **5 edges**, fewer than one hop, with nothing in the
   response saying it was cut. A caller sizing a blast radius gets a wrong answer.
2. **`GET /v1/queue/latency` is labelled `kind: "fact"`** while monetising elapsed
   waiting as staffed time. The percentiles are a fact; the $95/hour multiplication
   is a judgment, and `rules::queue-starvation`'s own text says so.
3. **`POST /v1/causal` quotes whichever finding you asked about.** Per-node latency
   ratios run 28.3×–45.5×, so the same incident reads "rose 28.3x" or "rose 45.5x",
   and its utilisation hop (−91.4%) is a constant in the code — the real telemetry
   shows 31.4% during the episode against 36.4% the week before.

**And what Layer B should do differently:** collapse findings by `rootCauses` before
ranking anything; never sum `impact_gpu_hours` across `impact_kind`; express
draining as a cost rather than a saving; add a `gpu_hour_weighted_sm_util` column to
`/v1/scaling/efficiency`; and return each outcome's *busy* hours in
`/v1/waste/breakdown`, which would settle the CANCELLED argument in the response
itself.

---

## Running it

```bash
# data/ first -- see data/README.md, steps 1-4 (make prep, make generate, make check-data)
docker compose up          # API on :8000, dashboard on :3000
```

The dashboard runs its own analysis at startup, including the 13 scheduler
simulations behind tile 4 — about 90 seconds on a laptop, so the first start is
slow. `DASH_SIM=0` skips the simulation and drops tile 4.

Then the analysis, any single case:

```bash
python3 analysis/case2_recoverable.py     # or case1..case9b, api_review, mcp_demo
make mcp-demo                             # drive the MCP server, write the transcript
make validate CLAIMS=claims.json URL=http://localhost:3000
```

The dashboard re-prices from the header (`$ /GPU-hour`), and asks
`GET /v1/efficiency/summary?usd_per_gpu_hour=N` to re-price its own waterfall, so a
changed rate comes back tagged `2026-Q3+custom`.
