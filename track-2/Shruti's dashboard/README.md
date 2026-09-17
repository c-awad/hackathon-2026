# Shruti's dashboard — three questions on screen, the analysis behind a button

Independent of `track-2/dashboard/`. Nothing here reads or writes that folder.

## The idea

A CFO gets three numbers and one picture per screen. Anyone who wants the workings
presses **Generate full report** and gets all of it in one page, printable and
downloadable as markdown.

The dashboard surface is deliberately tiny:

| Tab | Three numbers | One picture | One list |
|---|---|---|---|
| 1 — Where the money went | $1.49M spent · 39¢ of each dollar computed · 17¢ finished a job | the spend wheel | Current Spend |
| 2 — Where to cut | $359K cuttable · $297K target · $235K of it safe | the same wheel with the cut hatched out | Proposed Actions |
| 3 — What it costs if we're wrong | $235K confident · $124K judgment call · $101K we'd kill by mistake | — | four calls, colour-coded |

No tables, no sliders, no glossary on the tabs. `verify.py` and the smoke test both
fail the build if a tab grows a second chart, a table, a heading of its own, or a
fourth headline number.

**Tabs 1 and 2 are the same screen twice.** Same layout, same wheel at the same size,
and the same six rows in the same order — row four is "Second GPU sat idle" on both.
Only the right-hand column changes, from what each bucket cost to what we propose
doing about it, so the CFO can flip between the two tabs and read straight across.

## What sits underneath

Six buckets carry through everything, in the same order with the same colour. Every
GPU-hour lands in exactly one, so the first column sums to the whole bill and the
second sums to the point estimate — `build.py` asserts both on every run.

| Bucket (tab label) | Now | Cut | If we're wrong |
|---|---|---|---|
| Reserved but never used | $212K | **$205K** | $46K at stake, low risk |
| Barely used | $213K | **$106K** | $108K at stake, **high risk** |
| Didn't need a GPU | $31K | **$31K** | $7K at stake, low risk |
| Second GPU sat idle | $79K | **$18K** | $18K at stake, medium risk |
| Ran out of time | $111K | — | $111K, **not a cut** |
| Used normally | $839K | — | not a cut |
| **Total** | **$1.49M** | **$359K** | |

The tab shows the short label; the report shows the precise one ("Held a GPU and never
used it") along with the definition.

## Run it

Needs `data/prepped/jobs.parquet` and `gpus.parquet` (steps 1–2 of `data/README.md`).

```bash
cd track-2
.venv/bin/python "Shruti's dashboard/build.py"      # -> data.json, plus cross-checks
cd "Shruti's dashboard" && python3 -m http.server 3100
```

Then open http://127.0.0.1:3100 in a normal browser. Port 3100 keeps it clear of the
`:3000` submission slot and the API on `:8000`. Opening `index.html` as a file will not
work — the page fetches `data.json`, which browsers block over `file://`.

```bash
.venv/bin/python "Shruti's dashboard/verify.py"     # data contract + spine reconciliation
node /tmp/dash_smoke.mjs                            # renders app.js against a DOM stub
```

The three tabs are reflected in the URL hash (`#tile2`), so one can be linked or
reloaded into.

## The report

Built on click, once, from the same `data.json` — no second request, no server.

1. **Where the money went** — the three-stage funnel (paid for → computing → finished
   work, with what is lost at each step), how busy the card was inside each bucket, how
   jobs ended with the computing part solid, and who holds the capacity against a
   dashed line for everyone spending equally. Then the six buckets in full.
2. **Where to cut** — cautious, best-guess and optimistic totals against the 20%
   target; what each bucket returns and who has to act; the grace-period sweep, which
   shows the idle kill barely depends on the grace because these jobs sit unused for
   days.
3. **What it costs if we're wrong** — all 18 idle-kill policies at a one-hour grace,
   priced with capacity freed beside work destroyed; the same question answered two
   ways (cancelled-as-waste, the brief's 83%, row- versus hour-weighting); and the two
   machine rankings that disagree, with rows flagged where one researcher owns half the
   failures.
4. **What this data cannot tell us**, which bounds everything above.

**Download (.md)** writes the whole thing as markdown with 11 tables. **Print / PDF**
hides the app chrome and page-breaks on the section headings.

## Files

| | |
|---|---|
| `build.py` | prepped tables → `data.json`, printing 12 cross-checks |
| `verify.py` | asserts every field `app.js` reads exists; prints what each tab shows |
| `index.html`, `styles.css`, `app.js` | the page: no frameworks, no network calls, no build step |
| `data.json` | every number on the page and in the report |
| `_measure.html` | scratch harness for the one-fold check below; not part of the dashboard |

## Filling exactly one fold

A tab fills the viewport and never scrolls — no dead space at the bottom, nothing
below the fold. The page itself doesn't scroll; `main` does, which is what gives the
flex chain (`main > .tile > .two-col > .rows`) a definite height to divide up. With
only a `min-height: 100vh` on `body` the chain grows to fit its content instead of
shrinking into the viewport, which is the bug that made 1280×720 overflow by 88px.

Three rules keep the diagram's size out of the content's hands:

- `.two-col > .fig` has `aspect-ratio: 6/7`, so the panel's **width follows its own
  height**. However long an action's text is, it cannot resize the wheel.
- The wheel is `position: absolute` inside that panel, so its intrinsic size never
  stops the tab from shrinking on a short screen.
- The caption reserves exactly two lines, so a caption that wraps at one width can't
  make tab 2's wheel a different size from tab 1's.

`_measure.html` reports where every block lands, so this is checkable rather than
assumed. Comparing the two tabs' output is the test that they still match:

```bash
CH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
m() { "$CH" --headless --virtual-time-budget=2500 --window-size=$1,$2 \
  --dump-dom "http://127.0.0.1:3100/_measure.html?tab=$3&w=$1&h=$2" \
  | grep -o '<title>[^<]*</title>' | sed 's/<[^>]*>//g'; }
diff <(m 1440 800 tile1) <(m 1440 800 tile2) && echo "tabs 1 and 2 match"
```

Verified identical, with `page` equal to the viewport and `scroll=0`, at 1280×720,
1366×768, 1440×800, 1600×900, 1920×1080 and 2560×1440. The wheel scales with the
window — 275px at 1280×720, 358px at 1440×800, 872px at 2560×1440 — and the rows
share the leftover height evenly, 48px to 171px each.

Text scales with the same viewport: one `--fs` on `:root` (~13.5px at 1280×720, 15px
at 1440×800, 20px at 1920×1080, 24px at 2560×1440) and every other size is a `rem`
multiple of it. Button padding stays in `px`, so the hit target does not shrink
when the label does.

Below 1080px the two columns stack and the page scrolls normally: the aspect-ratio
panel is released, rows size to their text, and the wheel is centred at 340px.

Add `&why=1` to the measure URL to dump the computed flex chain when something
overflows, or `&report=1` to open the report first — it scrolls inside `main`, so it
is worth re-checking whenever the shell's overflow changes.

## What it does not depend on

`data/synthetic/` and the API on `:8000` are both optional — neither is read. The one
rule the page needs, `rules::gpu-imbalance`, is **recomputed** in `build.py` from
`gpus.parquet` (2+ cards, busiest ≥ 20% SM, spread > 30 points, wall > 1 h), reproducing
the finding exactly: the same 689 jobs, and 14,558 idle card GPU-hours against the
finding's 14,559.

That matters for the third section. A report arguing that a rule overstates its impact
should be able to compute the rule itself rather than quote it.

## Checks, printed on every build

```
ok  spine sums to the whole bill              594,005      594,004
ok  cut column sums to the point estimate     143,763      143,763
ok  gpu-imbalance jobs                            689          689
ok  gpu-imbalance idle GPU-h                   14,558       14,559
ok  finished without the GPU, GPU-h            12,301       12,301
ok  never used it, GPU-h                       84,896       84,896
ok  barely used it, GPU-h                      85,368       85,368
ok  busy work killed by clock, GPU-h           44,421       44,421
ok  bursty jobs (avg<5, peak>=50)               2,564        2,564
ok  point estimate GPU-h                      143,763      143,763
ok  low estimate GPU-h                         80,767       80,767
```

Expected values come from `track-2/ANALYSIS.md`.

## Known gaps before this could be submitted

- Serves on `:3100`, not the `:3000` the brief requires, and is not in
  `docker-compose.yml`. The folder name's space and apostrophe will need handling in a
  Docker build context.
- The interactive policy simulator was cut from the dashboard to keep it calm; the
  report shows the 18 policies at a one-hour grace as a static table, so the other
  126 combinations in `data.json` are computed but never displayed.
- No drill-down to individual job IDs yet, and no use of the MantisGrid API or its MCP
  tools, both of which the judging criteria ask about.
- `claims.json` is not written from these numbers.

## Caveat carried on the page

MIT SuperCloud publishes this as a four-month sample and says it is not appropriate for
estimating system utilization. Every figure describes the sample over its window, not
the cluster.
