# MCP transcript — asking the server where to cut GPU spend

Server: `python -m mcp_layer.server` over stdio. **13 tools**: `health`, `list_findings`, `causal`, `neighbor`, `detect`, `list_rules`, `price_book`, `efficiency_summary`, `waste_breakdown`, `queue_latency`, `scaling_efficiency`, `underperforming`, `recommendations`.

Every call below is a real tool call against the running server; the numbers are the server's own output.

## 1. `health` — what is loaded

```json
{
 "status": "ok",
 "findings": 11979,
 "resources": 77399
}
```

## 2. `recommendations` — the answer an agent would take at face value

- **Move sub-10% utilization workloads to shared allocation** — 53,430 USD (21,372 GPU-h), effort `medium`, `kind: judgment`, confidence **0.61**, citing 20 findings
- **Drain the top 5 underperforming nodes** — 57,226 USD (22,890 GPU-h), effort `low`, `kind: judgment`, confidence **0.58**, citing 20 findings

Both are `kind: judgment`. The tool description says a judgment must be validated against `causal` before acting, so that is the next call.

## 3. `underperforming` — the machines behind that recommendation

| Machine | Findings | Impact GPU-h |
|---|---|---|
| `r4605940-n772143` | 259 | 2,230.4 |
| `r7317916-n772143` | 165 | 1,188.9 |
| `r3974592-n172107` | 164 | 7,526.1 |
| `r4144777-n172107` | 154 | 4,267.5 |
| `r7317916-n303509` | 146 | 7,677.4 |

`kind: judgment`, confidence 0.61. Its own provenance says: *finding_count_per_resource@v1* — and the docstring warns it does not read `rootCauses`.

## 4. `causal` — validating the recommendation

The recommendation cites **20 findings**. Passing each to `causal`: **5 resolve to anything at all**, 15 come back `findings: []` with a message saying there is nothing upstream to resolve to.

So the citation is not evidence about those machines. It is a list of unrelated job-level findings that happen to sit on them -- wall-clock kills, idle sessions, jobs that never computed. **A drain list cannot be built out of findings that have no cause.**

The findings on those same machines that *do* carry a `rootCause` are the array-task failures. Asking `causal` about 3 of them:

| Finding | On machine | Resolves to | Top score | Each machine scores |
|---|---|---|---|---|
| `d3c2e41b` | `r7317916-n772143` | `array/31811330654` (k8s:job) | **1.0** | 0.15, 0.1, 0.1, 0.1 |
| `89616802` | `r3974592-n172107` | `array/4316447703` (k8s:job) | **1.0** | 0.4, 0.3, 0.25, 0.05 |
| `85d2ec4a` | `r3974592-n172107` | `array/34342561208` (k8s:job) | **1.0** | 0.167, 0.125, 0.083, 0.083 |

**The array scores 1.0; the machines score a fraction of it** (0.05-0.4, each machine's share of that array's failures). Failures spread thinly across many machines is how you know the machines are not the cause -- if one were faulty, its failures would concentrate on it. One broken submission script, not five broken machines.

## 5. `list_findings` + `causal` — 121 findings, one cause

`list_findings(detector_id="rules::filesystem-latency-degraded")` returns node-scoped findings such as `35aa893a`: *Storage latency degraded on r1039410-n172107*

`causal` on it: **pvc/scratch-lustre-02 degraded — filesystem p99 latency rose 30.3x, affecting 121 nodes** (confidence 0.74).

| Culprit | Type | Score |
|---|---|---|
| `pvc/scratch-lustre-02` | k8s:persistentvolumeclaim | 0.88 |
| `r1039410-n172107` | k8s:node | 0.31 |
| `r1039410-n750018` | k8s:node | 0.31 |
| `r1039410-n772143` | k8s:node | 0.31 |
| `r1051355-n172107` | k8s:node | 0.31 |

One volume at 0.88, machines at 0.31. **Nothing to drain.**

## 6. `list_rules` — what was checked and came back clean

24 rules armed, 1 `CLEAR`: `rules::gpu-pcie-saturated` (Evaluated clean — no findings)

A rule that ran and found nothing is evidence: data movement is not the bottleneck here, so "fix the data pipeline" stays off the list.

## 7. `efficiency_summary` + `waste_breakdown` — the facts (`kind: fact`)

- allocated: 594,004 GPU-h (100.0%)
- computed: 228,904 GPU-h (38.5%)
- computed_completed: 100,789 GPU-h (17.0%)
- monetised: 1,485,010 USD, `2026-Q3`, `kind: fact`

By outcome: COMPLETED 229,041, CANCELLED 203,930, TIMEOUT 107,952, FAILED 50,033, NODE_FAIL 2,028, UNDECODED_11 1,021, UNDECODED_1024 0

## 8. `efficiency_summary(usd_per_gpu_hour=4.0)` — modelling a different rate

2,376,015 USD, tagged `2026-Q3+custom` — the server marks a re-priced answer, so a price change never reads as an infrastructure change.

## 9. `queue_latency` — the one label we disagree with

p50 8s, p99 18.3h, total 98,214 h over 74,838 jobs → **9,330,307 USD**, `kind: fact`.

The percentiles are a fact. The monetisation is not: it prices every job's wait as staffed time, and 53% of jobs are array tasks, so one person with 1,000 pending tasks is counted 1,000 times. Merged per person it is 4,997 h, and 3,719 h past a 4-hour target.

## What the agent should answer

**Cut:** idle allocations that never ran a kernel (~$205K), CPU work sitting on GPUs (~$79K), and two-GPU jobs using one card (~$36K).

**Do not cut:** the five machines `recommendations` names ($57,226 claimed). `causal` resolves their findings to Slurm arrays and one storage volume, not to the machines. Draining them removes ~1,680 GPU-h of capacity a week and the failing scripts fail wherever they land next.

**The workflow that produced that answer is two calls long:** ask for the recommendation, then ask `causal` what is underneath it. The recommendation endpoint never makes the second call — which is the whole finding.
