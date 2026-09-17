# Track 2 — What the MantisGrid API tells you, and where it is wrong

A review of every endpoint, one at a time. For each: what we called, what it
answered, what we checked it against, and whether a CFO could act on it.

Script: `analysis/api_review.py` (run from `track-2/`, with the API up). Raw
output: `analysis/out_api_review.json`. The data-side working is the companion
document, [`ANALYSIS.md`](ANALYSIS.md), case by case.

**Two layers, judged differently.**

- **Layer A** mirrors MantisGrid's production API. We treat it as ground truth about
  what the detectors found, and we checked it anyway.
- **Layer B** is proposed and the brief invites pushback. Every verdict below is
  backed by a recomputation from `data/prepped/`, not an opinion.

**Every Layer B response carries `kind`:** `fact` (deterministic, recomputable) or
`judgment` (a model said so). We found one endpoint whose `kind` is wrong.

## Verdicts at a glance

| Endpoint | Layer | `kind` | Our verdict |
|---|---|---|---|
| `POST /v1/causal` | A | fact | **The best endpoint in the API.** Everything ranked should pass through it first |
| `GET /v1/policies/rules` | A | fact | Read it *alongside* the findings; a CLEAR rule is evidence |
| `POST /v1/events/findings` | A | fact | Trust it as a corpus; never sort by severity and call that cost |
| `POST /v1/neighbor` | A | fact | Useful for shared-dependency tests, but **silently truncates at 500 nodes** and returns a broken graph at 2 hops |
| `POST /v1/detect/{id}` | A | fact | Fine as a health check on the detector set |
| `GET /v1/efficiency/summary` | B | fact | **Correct and recomputable.** The one Layer B number we ship as-is |
| `GET /v1/waste/breakdown` | B | fact | Rows are right; refuse to total them without saying which rows you counted |
| `GET /v1/price-book` | B | fact | Use it, and pass overrides so a price change shows as `+custom` |
| `GET /v1/scaling/efficiency` | B | judgment | Row-weighted. Recompute hour-weighted before concluding anything about money |
| `GET /v1/queue/latency` | B | **fact (wrong)** | Percentiles yes; the monetised figure is 6.3× the GPU bill |
| `GET /v1/resources/underperforming` | B | judgment | **Do not act on the node ranking** |
| `GET /v1/recommendations` | B | judgment | **The weakest endpoint.** Re-derive every recommendation |

---

# Layer A — the real API

## `POST /v1/causal`

**The endpoint that earns its place.** It resolves a *cluster* of findings to the
one resource underneath them.

| We asked about | It answered | Top score | Next three |
|---|---|---|---|
| `filesystem-latency-degraded` | `pvc/scratch-lustre-02` degraded, "affecting 121 nodes" | **0.88** | 0.31, 0.31, 0.31 |
| `array-task-failure` | `array/65192801012` — 22 of 22 tasks failed, exit code 256, spread over 10 machines | **1.0** | 0.136, 0.136, 0.136 |
| `gpu-low-utilization` | `findings: []` with a message | — | — |

**Three things this gets right:**

1. **One cause, not 121 problems.** All 121 storage findings resolve to one volume.
2. **The spread is the evidence.** For an array, each machine scores ~0.14. Low,
   even scores across many machines are how you know the machines are innocent; if
   one were faulty the failures would concentrate on it.
3. **An empty answer is correct behaviour.** A finding with no `rootCauses` has
   nothing to resolve to, and the endpoint says so in `message` rather than
   inventing a chain.

**Two things we would change:**

- **The latency figure depends on which finding you ask.** The sentence is built
  from the *requested* finding's own `fs_latency_p99_ratio`, and per-node ratios run
  **28.3× to 45.5×**, so the same incident reads "rose 28.3x" or "rose 45.5x". A
  volume-level answer should quote one volume-level number.
- **The second chain hop is asserted, not measured.** `gpu_sm_utilization`
  `abrupt_drop` **−91.4%** is a constant in `api/main.py`. The real telemetry on
  those 121 machines shows 31.4% utilization during the episode against 36.4% the
  week before — a five-point dip. A milder slowdown is consistent with the data; a
  91% collapse is not. (The incident is the corpus's one synthetic scenario, so the
  jobs underneath simply carried on.)

## `GET /v1/policies/rules`

24 rules armed, **1 reporting `CLEAR`** (`rules::gpu-pcie-saturated`) — and the CLEAR one is the most useful
single fact in the catalogue.

`rules::gpu-pcie-saturated` watches for the PCIe bus above 80% of link capacity
while the GPU idles. Peak observed here is **4,240 MB/s of a 15,754 MB/s link
(27%)**, a factor of three short. **Data movement is not what holds these GPUs
back**, so "fix the data pipeline" never reaches our recommendation list. A rule
that ran and found nothing is evidence, and an endpoint that hides it would have
cost us that conclusion.

The rules also **withhold cause on purpose**: `node-elevated-failure-rate` reports
a rate against the cluster and says nothing about why. That is honest, and it is
why case 6 had to triage all 113 firings itself.

**What we would change:** ship each rule's threshold in the response. Today they
live only in `docs/rules.md`, so a dashboard cannot show a viewer what a finding
actually tested.

## `POST /v1/events/findings`

The corpus: **11,979 findings across 23 detectors**.

- **Every call is capped at 100 results**, filtered or not, so a full sweep needs
  ~120 calls and a per-detector count from this endpoint means "up to 100". Get real
  counts from `/v1/policies/rules`, which carries a `findings` number per rule.
  **What we would change:** return a total count and a cursor.
- **`isActive` hides three quarters of it.** **8,691 findings (73%)** are
  `RESOLVED` / `isActive: false`; the active set is **3,288**. That is the right
  default for an on-call view and the wrong one for a quarterly cost review, where
  the aged-out findings are most of the money.
- **Severity is not cost, and the gap is 39×.** Job-scope findings:

  | Severity | Findings | Impact GPU-h | At $2.50 |
  |---|---|---|---|
  | CRITICAL | 31 | 7,772 | $19,430 |
  | HIGH | 3,215 | 226,110 | $565,275 |
  | LOW | 8,254 | **303,782** | **$759,455** |

  `CRITICAL` is reserved for the scheduler's 31 node failures plus the one hardware
  fault — it tracks **availability**, not money. The largest single `LOW` finding is
  **3,160 GPU-hours ($7,899)** on its own. Sorting by severity and calling it a cost
  ranking is one query away, and it would point a CFO at $19K while $759K sits in
  the rows below.

## `POST /v1/neighbor`

The resource graph: **77,399 resources** (74,849 pods, 2,129 arrays, 225 machines,
195 user namespaces, 1 volume) and **198,601 edges** (`RUNS_ON` 81,521,
`CONTAINS` 74,849, `OWNS` 39,694, `MOUNTS` 2,537).

One hop out from the volume returns **500 nodes and 611 edges**. This is how you
test a shared-dependency hypothesis without trusting a recommendation.

**500 is a cap, not the answer, and the truncation breaks the graph.**
`api/main.py:142` does `seen = set(list(seen)[:500])  # keep responses answerable`.
The volume has **2,537 `MOUNTS` edges**, so one hop is already truncated to a fifth
of its neighbours. Worse, the cap is applied to the node set *before* edges are
collected, so asking for two hops returns **500 nodes and 5 edges** — fewer edges
than one hop, and a graph whose nodes are mostly unconnected. A caller who walks
this to decide a blast radius gets a silently wrong answer, with nothing in the
response to say it was cut.

**It also exposed a gap in the incident.** Pods mounting the volume were active on
**159 machines** during the episode, but only **121** have a finding. Either the
detector missed 38 machines or they were not affected, which would weaken the case
against the volume. The graph is wider than the detector's blast radius, and only
the graph shows you that.

**What we would change:** say when the response was truncated (a `truncated: true`
flag and the real neighbour count), apply the cap to a *connected* subgraph rather
than to a set, and return edge direction and per-type counts so a caller can walk
the graph without also holding the parquet.

## `POST /v1/detect/{integration_id}`

Returns per-detector counts; HTTP 200 for any integration id we passed. Useful as
a health check on the detector set, not as analysis.

---

# Layer B — the proposed business layer

## `GET /v1/efficiency/summary` — correct

The only Layer B figure we put on the dashboard unchanged.

| Row | Endpoint | Our recomputation |
|---|---|---|
| allocated | 594,003.8 | 594,004 (`jobs.parquet.gpu_hours.sum()`) |
| computed | 228,903.8 | 228,904 (hours × `sm_util_avg`) |
| computed_completed | 100,788.8 | 100,789 (same, COMPLETED only) |

Reproducible to the hour, and its `provenance.caveat` is the honest part: SM
utilization is a proxy, and a data-loader-bound or communication-bound job does
real work at low occupancy.

**What we would add:** a fourth row for allocation the cluster never computed on,
so the waterfall ends where the money is rather than where the work is.

## `GET /v1/waste/breakdown` — right to refuse a total

Every state matches our own groupby to the hour: COMPLETED 229,041, CANCELLED
203,930, TIMEOUT 107,952, FAILED 50,033, NODE_FAIL 2,028.

**It deliberately does not total the rows, and that restraint is correct.**
CANCELLED is the second-largest row and is not waste in itself: those jobs ran at
**34.3%** hour-weighted utilization against the cluster's 38.5%. Counting them as
waste would promise **116,692 GPU-hours** of work that was computing when someone
stopped it — and it swings the headline by about 2×.

**What we would add:** each state's *busy* (SM-weighted) hours beside its allocated
hours. That single column ends the CANCELLED argument in the response itself.

## `GET /v1/price-book` — use it, and push prices through it

`$2.50` per GPU-hour, `$95.00` per engineer-hour, `epoch_offset` for dates.

**The engineer rate is 38× the GPU rate.** That ratio is the reason anything
monetised as human time dominates every other number on a dashboard, and it is why
the queue endpoint below goes so wrong. Overrides work and re-tag the response
`2026-Q3+custom`, which is a good design: a price change is then visibly not an
infrastructure change.

**What we would change:** version the engineer rate separately. It is an assumption
about people, not a hardware price, and it deserves its own provenance.

## `GET /v1/scaling/efficiency` — right caveat, wrong weighting

It reports median SM utilization per width band plus `share_under_5pct` and
`share_over_80pct`, and its caveat says to read the shares rather than the median
because the distribution is bimodal. Correct.

**But every figure is row-weighted, and money is hour-weighted.** Recomputed by
GPU-hours:

| GPUs per job | Hour-weighted utilization |
|---|---|
| 1 | 29% |
| 2 | 38% |
| 3–4 | 42% |
| 5–8 | **77%** |
| 9–16 | 67% |
| 17–64 | **32%** |

So "wide jobs are wasteful" is a job-count artefact: the 398 jobs of 9+ GPUs hold
**16.6% of all GPU-hours at 59% utilization**. The honest reading is that
efficiency rises with width to about 16 GPUs and **falls back at the very top** —
the 17–64 band is the one worth asking about, and it is invisible in the
row-weighted view.

**What we would add:** a `gpu_hour_weighted_sm_util` column. Without it the
endpoint invites exactly the wrong cut.

## `GET /v1/queue/latency` — the one mislabelled `kind`

```
p50 8 s · p90 2.2 h · p99 18.3 h · max 12.2 d · total_wait_hours 98,214
monetized: $9,330,307   kind: "fact"
```

**$9.33M is 6.3× the entire $1.49M GPU bill.** Three faults:

1. **It measures from submission, not eligibility.** `wait_sec = time_start −
   time_submit` includes **22,880 h (23%)** of time before jobs were eligible to
   run. All 30,713 jobs with such a gap are array tasks, held by their own
   dependencies or throttling. Real queueing is 75,334 h.
2. **It counts jobs as people.** 53% of jobs are array tasks. Merged per person,
   the same waiting is **4,997 h**, and **3,719 h** past a 4-hour target.
3. **`kind` says `fact`.** The percentiles are a fact; multiplying them by a salary
   is a judgment, and `rules::queue-starvation`'s own text says so: *"elapsed
   wall-clock between submit and start, NOT staffed time — nobody sits watching a
   scheduler."* The literal version — interactive sessions, a person at a keyboard —
   is **0.8 hours in four months**.

**What we would change:** measure from `time_eligible`, group by person, and mark
the monetised field `kind: "judgment"` with the blocking assumption in
`provenance`.

## `GET /v1/resources/underperforming` — do not act on the node ranking

Nodes are ranked by **finding count**, and the response admits it does not read
`rootCauses`.

| Machine | Findings | Of which array-task failures | Our triage (case 6) |
|---|---|---|---|
| `r4605940-n772143` | 259 | 209 | user_code, user_code |
| `r7317916-n772143` | 165 | 134 | user_code, user_code |
| `r3974592-n172107` | 164 | 122 | user_code |
| `r4144777-n172107` | 154 | 104 | cannot_determine, user_code, cannot_determine |
| `r7317916-n303509` | 146 | 95 | user_code, workload_mix |

- **The counts are other people's scripts.** Each machine carries 95–209
  array-task findings, and `/v1/causal` resolves those to the array at score 1.0
  with the machines at 0.136.
- **Fifth place is a coin toss.** Three machines tie at 146 findings, so which
  machine you are told about depends on dict order.
- **The one real hardware fault ranks 21st.** `r216287-n200569`, where three
  unrelated people crashed with SIGBUS and never did so on any other machine, has
  fewer findings than any of the five.
- **The user ranking lists people.** Ranking by unsuccessful GPU-hours is
  defensible arithmetic, but the brief is explicit that a dashboard ranking
  employees by waste is a hostile dashboard. We show it as capacity, never as blame,
  and keep owners hashed.

**What we would change:** collapse findings by `rootCauses` before ranking, rank
machines on evidence that follows the *machine* (a multi-owner crash signature,
located node failures, excess failures after adjusting for each owner's own rate),
and break ties explicitly or return all tied machines.

## `GET /v1/recommendations` — the weakest endpoint

Two recommendations, both `kind: judgment` with confidence 0.58–0.61. The honest
labelling is the best thing about them.

**`rec_drain_nodes`: "Drain the top 5 underperforming nodes", $57,226, effort
`low`.**

- The saving is the sum of those five machines' job-scope `impact_gpu_hours`
  **across `impact_kind`** — `lost` + `consumed` + `unused_capacity` — which
  `docs/rules.md` says produces a number that means nothing.
- **Draining is not a saving.** It removes **1,680 GPU-hours a week** of capacity
  (about **$55K** over a 13-week quarter) and the failing arrays reschedule
  elsewhere and fail there.
- Effort `low` is true of the action and false of the consequence.

**`rec_lowutil`: "Move sub-10% utilization workloads to shared allocation",
$53,430.**

- It is **35% of `gpu-low-utilization`'s 61,063 GPU-hours**, and the 0.35 is a
  constant in `api/main.py`, not something the data supports.
- It cites **20 of 95** findings, and **21 of those 95 jobs use 16 or more GPUs**,
  which a fractional-GPU queue cannot serve.

**What we would change:** route every recommendation through `/v1/causal` before
publishing it, express draining as a cost rather than a saving, never sum across
`impact_kind`, and cite all contributing findings rather than the first 20.

---

# What we built on top

The dashboard on `:3000` uses the API where it is right and replaces it where it is
not:

| Used as-is | Rebuilt from `data/prepped/` |
|---|---|
| `/v1/price-book` (both rates) | the recoverable total, deduplicated to one class per job |
| `/v1/efficiency/summary` (the waterfall) | spend by outcome and by utilization band |
| `/v1/causal` (live, in tile 3) | the three ranked actions and their ranges |
| `/v1/policies/rules` (the CLEAR rule) | card imbalance, from `gpus.parquet` per card |
| `/v1/recommendations` (quoted, then rebutted) | hardware-attributable failures, and all 113 triage verdicts |
| `/v1/resources/underperforming` (quoted, then rebutted) | every queue figure |

**The single most useful thing in the API is that two of its own endpoints
disagree.** `/v1/recommendations` says to drain five machines; `/v1/causal` says
the culprit is an array at score 1.0 with those machines at 0.136. Tile 3 of the
dashboard shows both answers side by side, because the disagreement is the finding:
**a ranking that never asks "what is underneath this?" turns one broken script into
a list of machines to switch off.**

---

## How to reproduce this

```bash
cd track-2
docker compose up -d api
python3 analysis/api_review.py        # prints every check, writes out_api_review.json
```

Numbers here were measured on the corpus that `make check-data` verifies, so they
should match yours exactly.
