# MantisGrid Hackathon 2026 — Track 2 submission

**Cluster efficiency: where to cut $1.49M of GPU spend, and what not to touch.**

Everything for this submission lives in [`track-2/`](track-2/).

| | |
|---|---|
| **The dashboard** | `cd track-2 && docker compose up` → **http://localhost:3000** (five tabs; the same data as one long page at `/classic/`) |
| **The report** | [`track-2/REPORT.md`](track-2/REPORT.md) |
| **The claims** | [`track-2/claims.json`](track-2/claims.json) |
| **The working** | [`track-2/ANALYSIS.md`](track-2/ANALYSIS.md) — case by case, 1 to 9b |
| **The API review** | [`track-2/API_ANALYSIS.md`](track-2/API_ANALYSIS.md) — every endpoint, and three bugs |
| **The scripts** | [`track-2/analysis/`](track-2/analysis/) — one per case, plus the scheduler simulator |

This repository is a fork of the organisers' `hackathon-2026-official`, so the
original briefs and guides are still in place (`track-2/README.md`,
`track-2/docs/`), with our work added alongside them. `track-1/` is untouched.

## Running it

```bash
cd track-2
# 1. get the data -- see data/README.md, steps 1-4
curl -O https://mantisgrid-hackathon.s3.us-east-1.amazonaws.com/track-2-raw.zip
unzip track-2-raw.zip -d data/raw
make prep && make generate && make check-data     # prints "Your data matches."

# 2. bring it up
docker compose up                                  # API on :8000, dashboard on :3000
```

The dashboard builds its data on startup by running the analysis over
`data/prepped/`, including 13 runs of the scheduler simulation (about 90 seconds on a laptop, so the
first start is slow; set `DASH_SIM=0` to skip it). It serves `:3000` and proxies `/api/*` to the API service,
because the API sends no CORS headers and the price control is a real API call.

```bash
make validate CLAIMS=claims.json URL=http://localhost:3000   # check before submitting
make mcp-demo                                                # drive the MCP server
python3 analysis/case2_recoverable.py                        # any single case
```

## Who built what

The dashboard's **UI design is Shruti Doshi's** — the tabbed shell, KPI rows, spend
wheel, row components and stylesheet come from her dashboard, preserved in
`track-2/Shruti's dashboard/`. The version served on `:3000` puts that design on top
of the shared data pipeline (`dashboard/build.py`): one waste class per job, live
`POST /v1/causal`, the price-book override through the `/api` proxy, and the
scheduler simulation behind tab 4.

## What we found, in short

- **$359K recoverable** of $1.49M (range $202K–$491K). Most of it is GPUs nobody was
  using: 97,196 GPU-hours never ran a single kernel.
- **One machine to drain**, not the 121 the storage findings suggest and not the 5
  the API recommends. `r216287-n200569` failed 140 of 144 jobs with a SIGBUS
  signature three unrelated owners never produced anywhere else, and the scheduler
  never marked it down.
- **Hardware caused 0.8% of failures** (145 of 18,587). Almost everything else is
  user code.
- **The queue is a quota problem, not a capacity one.** In 90% of waits over an
  hour the researcher was already at their own concurrency cap while a median 287 of
  450 GPUs sat free. An elastic quota plus an idle timeout removes 96% of the
  modelled waiting: **1,267 person-hours** returned to researchers (up to $120K if
  that waiting fully blocks them), at no capacity cost.
- **Three API bugs**, with file and line, in `track-2/API_ANALYSIS.md`.

## AI models, assistants and frameworks we used

**All of the code, analysis and prose in this submission was produced with
[Claude Code](https://claude.com/claude-code) in an interactive session, running
Claude Opus 5 (1M context) for almost all of it and Claude Fable 5.1 for the final
case (case 10, the credits pool).** No other AI model, agent framework or coding assistant
was used, and no LLM is called at runtime by anything we shipped: the dashboard and
every analysis script are plain Python and JavaScript over the prepped Parquet
tables and the MantisGrid API.

Specifically AI-generated: the nine analysis scripts in `analysis/`, the scheduler
simulator, `dashboard/` (build, server, page and charts), `claims.json`, and the
three documents (`REPORT.md`, `ANALYSIS.md`, `API_ANALYSIS.md`).

What the team did: chose the track and the questions to ask, directed each case,
pushed back on numbers that looked wrong, and made the judgement calls the brief
asks teams to defend — whether cancelled jobs count as waste, where to set the
idle-timeout grace period and the elastic-quota threshold, and which findings were
worth arguing with. Several of the strongest results exist because the team asked
for them rather than because the model proposed them: the CPU-offload tiering, the
scheduler simulation and its per-user-quota model, the MCP transcript, the
dashboard's price control, and the credits pool — including the two design changes
that made it work (never reduce the lender's own quota; set the loan window to the
mean job length and gate on predicted runtime).

Corrections the team's questions forced, all recorded in the documents: the
"never ran a kernel" figure was initially overstated ($369K → $243K, because a
zero *average* is not a zero *peak*), the wide-job utilisation claim was not
monotonic once banded finely, and the first scheduler simulation omitted per-user
quotas and so reproduced only 1% of the observed waiting.

The MantisGrid API facsimile, its MCP layer (`track-2/mcp_layer/`), the data
preparation scripts and the findings generator are the **organisers'** code, not
ours.

## Data and licences

The data is not in this repository and must not be: MIT SuperCloud publishes it
under CC BY-NC-ND 4.0, which forbids redistributing anything derived from it. See
[`ATTRIBUTION.md`](ATTRIBUTION.md). Generate `data/` yourself with the steps above;
`make check-data` confirms your five files match the organisers' checksums, which
ours do.

MIT publishes this as a four-month **sample** of the cluster's jobs and notes it is
*"not appropriate for use in estimating system utilization"*. Every figure in this
submission describes that sample, and the documents say so wherever it matters.
