/* GPU spend review -- renders dashboard/data.json.
   Charts are inline SVG: sequential blue for magnitude, categorical hues only
   where series identity is the point, always with direct labels (the palette's
   light-mode aqua sits under 3:1, so labels and a table view are obligatory). */

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, kids = []) => {
  const n = document.createElementNS(tag === "svg" || SVG.has(tag) ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml", tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") n.textContent = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(kids)) if (c) n.appendChild(c);
  return n;
};
const SVG = new Set(["svg", "g", "rect", "path", "line", "text", "circle", "polyline"]);
const usd = (n) => n == null ? "--" : (Math.abs(n) >= 1e6 ? "$" + (n / 1e6).toFixed(2) + "M"
  : Math.abs(n) >= 1000 ? "$" + Math.round(n / 1000) + "K" : "$" + Math.round(n));
const usdFull = (n) => "$" + Math.round(n).toLocaleString("en-US");
const num = (n) => Math.round(n).toLocaleString("en-US");
const pct = (x) => (x * 100).toFixed(x < 0.1 ? 1 : 0) + "%";
/* hours keep two decimals below 100 -- a p90 of 2.03 h must not read as "2 h" */
const fmtv = (v, unit) => unit === "jobs" ? num(v)
  : (Math.abs(v) < 100 ? v.toFixed(2) : num(v)) + " " + unit;

/* ---------------------------------------------------------------- tooltip */
const tip = $("#tip");
function hoverable(node, html) {
  node.addEventListener("pointerenter", (e) => { tip.innerHTML = html; tip.style.opacity = 1; move(e); });
  node.addEventListener("pointermove", move);
  node.addEventListener("pointerleave", () => { tip.style.opacity = 0; });
  function move(e) {
    const r = tip.getBoundingClientRect();
    tip.style.left = Math.min(e.clientX + 14, innerWidth - r.width - 12) + "px";
    tip.style.top = Math.max(e.clientY - r.height - 12, 10) + "px";
  }
  return node;
}

/* ------------------------------------------------------------ bar chart */
// Horizontal bars. Magnitude -> one hue (sequential blue) unless `colors` given.
function bars(rows, opts = {}) {
  const { valueKey = "usd", labelKey = "label", fmt = usd, colors = null, height = 26, gap = 8 } = opts;
  const max = Math.max(...rows.map((r) => Math.abs(r[valueKey]))) || 1;
  const labelW = opts.labelW ?? 168, valueW = 86, w = labelW > 260 ? 820 : 640;
  const h = rows.length * (height + gap);
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": opts.aria || "bar chart" });
  rows.forEach((r, i) => {
    const y = i * (height + gap), v = Math.abs(r[valueKey]);
    const bw = Math.max(2, (v / max) * (w - labelW - valueW));
    svg.appendChild(el("text", { x: 0, y: y + height / 2 + 4, class: "lbl", text: r[labelKey] }));
    const fill = colors ? colors[i % colors.length] : "var(--series-1)";
    const bar = el("rect", {
      x: labelW, y: y + 3, width: bw, height: height - 6, rx: 4, fill, class: "mark",
      opacity: r.dim ? 0.45 : 1,
    });
    hoverable(bar, `<b>${r[labelKey]}</b><br>${fmt(r[valueKey])}${r.note ? "<br><span style='color:var(--text-secondary)'>" + r.note + "</span>" : ""}`);
    svg.appendChild(bar);
    svg.appendChild(el("text", { x: labelW + bw + 8, y: y + height / 2 + 4, class: "val", text: fmt(r[valueKey]) }));
  });
  return svg;
}

/* --------------------------------------------------- interval (low-point-high) */
function intervals(rows) {
  const max = Math.max(...rows.map((r) => r.high_usd)) * 1.05;
  const labelW = 300, w = 780, rowH = 34;
  const svg = el("svg", { viewBox: `0 0 ${w} ${rows.length * rowH + 22}`, role: "img", "aria-label": "estimate ranges" });
  const x = (v) => labelW + (v / max) * (w - labelW - 70);
  rows.forEach((r, i) => {
    const y = i * rowH + 14;
    svg.appendChild(el("text", { x: 0, y: y + 4, class: "lbl", text: r.title }));
    svg.appendChild(el("line", { x1: x(r.low_usd), x2: x(r.high_usd), y1: y, y2: y, stroke: "var(--series-1)", "stroke-width": 2, opacity: .35 }));
    [r.low_usd, r.high_usd].forEach((v) => svg.appendChild(el("line", {
      x1: x(v), x2: x(v), y1: y - 5, y2: y + 5, stroke: "var(--series-1)", "stroke-width": 2, opacity: .55 })));
    const dot = el("circle", { cx: x(r.usd), cy: y, r: 6, fill: "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": 2, class: "mark" });
    hoverable(dot, `<b>${r.title}</b><br>point ${usdFull(r.usd)}<br>range ${usdFull(r.low_usd)} &ndash; ${usdFull(r.high_usd)}<br>confidence ${r.confidence}`);
    svg.appendChild(dot);
    svg.appendChild(el("text", { x: x(r.high_usd) + 10, y: y + 4, class: "val", text: usd(r.usd) }));
  });
  svg.appendChild(el("text", { x: labelW, y: rows.length * rowH + 16, class: "lbl", text: "$0" }));
  svg.appendChild(el("text", { x: w - 70, y: rows.length * rowH + 16, class: "lbl", text: usd(max), "text-anchor": "end" }));
  return svg;
}

/* ---------------------------------------------------------------- tables */
function table(rows, cols) {
  if (!rows || !rows.length) return null;
  const t = el("table", {}, [
    el("thead", {}, el("tr", {}, cols.map((c) => el("th", { text: c.h, class: c.l ? "l" : "" })))),
    el("tbody", {}, rows.map((r) => el("tr", {}, cols.map((c) =>
      el("td", { class: (c.l ? "l " : "") + (c.mono ? "mono" : ""), text: c.f ? c.f(r) : (r[c.k] ?? "") }))))),
  ]);
  return t;
}
const tableWrap = (rows, cols, caption) => {
  const box = el("div", { class: "tablebox", style: "display:none" });
  if (caption) box.appendChild(el("p", { class: "note", text: caption }));
  box.appendChild(table(rows, cols));
  return box;
};

/* ------------------------------------------------- price: one rate, one scale */
/* Every GPU figure in data.json is priced at the price book's rate. Changing the
   rate rescales those (and only those -- blocks tagged priced_in:"engineer" are
   salary, not GPU time), and we ask the API to re-price its own waterfall at the
   same rate so the page shows ITS answer, tagged 2026-Q3+custom. */
let RAW = null, BASE = 2.5, RATE = 2.5;

const scale = (v, k = "") => {
  if (Array.isArray(v)) return v.map((x) => scale(x));
  if (v && typeof v === "object") {
    if (v.priced_in === "engineer") return v;
    return Object.fromEntries(Object.entries(v).map(([key, val]) => [key, scale(val, key)]));
  }
  if (typeof v === "number" && /usd/i.test(k)) return v * (RATE / BASE);
  return v;
};

fetch("data.json").then((r) => r.json()).then((d) => {
  RAW = d;
  BASE = RATE = d.meta.price_book.usd_per_gpu_hour || 2.5;
  const input = $("#rate");
  input.value = RATE.toFixed(2);
  const apply = () => {
    const v = parseFloat(input.value);
    if (!(v > 0) || v === RATE) return;
    RATE = v;
    draw();
  };
  input.addEventListener("change", apply);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
  controls();
  draw();
}).catch((e) => {
  $("#subtitle").textContent = "could not load data.json -- run dashboard/build.py";
  console.error(e);
});

function draw() {
  ["#hero", "#tile1", "#tile2", "#tile3", "#tile4", "#extras"].forEach((id) => { $(id).innerHTML = ""; });
  render(scale(RAW));
  priceCheck();
}

/* Ask the API to re-price its own waterfall at the current rate. Proof that the
   control is an API call, not arithmetic: the response comes back tagged
   2026-Q3+custom whenever the rate differs from the price book. */
function priceCheck() {
  const box = el("p", { class: "pricetag", id: "pricetag", text: "asking the API to re-price at $" + RATE.toFixed(2) + "/GPU-hour..." });
  $("#tile1").appendChild(box);
  fetch(`/api/v1/efficiency/summary?usd_per_gpu_hour=${RATE}`)
    .then((r) => r.json())
    .then((j) => {
      const m = j.monetized || {};
      box.innerHTML = `Live cross-check: <code>GET /v1/efficiency/summary?usd_per_gpu_hour=${RATE}</code> `
        + `returns <b>${usdFull(m.amount || 0)}</b> allocated, priced as `
        + `<b>${m.price_book_version || "?"}</b>`
        + (m.price_book_version && m.price_book_version.includes("custom")
          ? " &mdash; the API tags a re-priced answer, so a price change never reads as an infrastructure change."
          : " &mdash; the price book's own rate.");
    })
    .catch(() => { box.textContent = "API not reachable from the page; figures above are priced locally at $" + RATE.toFixed(2) + "/GPU-hour."; });
}

function render(d) {
  const c = d.meta.cluster, rec = d.tile2.recoverable;
  $("#subtitle").innerHTML = `${num(c.nodes)} machines &middot; ${num(c.gpus_per_node * c.nodes)} V100 GPUs &middot; `
    + `${num(c.jobs)} jobs from ${c.users} researchers &middot; ${c.window_days} days &middot; `
    + `priced at $${RATE.toFixed(2)}/GPU-hour `
    + (RATE === BASE ? `(price book ${d.meta.price_book.version})`
       : `(<b>${d.meta.price_book.version}+custom</b>, book rate $${BASE.toFixed(2)})`);

  /* ---- hero ---- */
  const overTarget = rec.point_usd >= rec.target_usd;
  $("#hero").append(
    el("div", { class: "hero" }, [
      el("div", {}, [
        el("div", { class: "figure", html: `${usd(rec.point_usd)} <small>recoverable of ${usd(c.usd)} spent</small>` }),
        el("p", { class: "range", html: `range ${usdFull(rec.low_usd)} &ndash; ${usdFull(rec.high_usd)} &middot; `
          + `${pct(rec.point / c.gpu_hours)} of capacity &middot; the 20% target is ${usdFull(rec.target_usd)} `
          + `<span class="${overTarget ? "ok" : "bad"}">(${overTarget ? "target met at the point estimate" : "target not met"})</span>` }),
      ]),
      el("div", { class: "kpis" }, [
        kpi(usd(d.tile2.actions[0].usd), "GPUs idle at zero, reclaimable"),
        kpi(d.hardware.point, `hardware-caused failures of ${num(d.hardware.failed_jobs_total)}`),
        kpi("1", "machine to drain (not 121, not 5)"),
        kpi(num(d.queue.person_hours_past_target), "person-hours waiting past 4h"),
      ]),
    ]),
    el("p", { class: "note", style: "margin-top:14px",
      html: `Read in 30 seconds: <b>most of the recoverable money is GPUs nobody was using</b> &mdash; `
        + `not machines to switch off and not people to chase. The two things the detection API `
        + `recommends most loudly (drain 5 machines, drain 121) would cost capacity and save nothing; `
        + `see tile 3.` }),
  );
  function kpi(v, l) { return el("div", { class: "kpi" }, [el("div", { class: "v", text: v }), el("div", { class: "l", text: l })]); }

  /* ---- tile 1: where the money is going ---- */
  const t1 = d.tile1;
  const wf = t1.waterfall.map((r) => ({ ...r, note: r.note }));
  $("#tile1").append(
    el("span", { class: "tileno", text: "Tile 1" }),
    el("h2", { text: "Where the money is going" }),
    el("p", { class: "sub", text: "Every GPU-hour the cluster handed out, then how much of it the cards were actually computing on, then how much of that produced a finished result." }),
    el("div", { class: "chartrow" }, [
      el("div", {}, [
        el("h3", { text: "From allocated to useful work" }),
        bars(wf, { aria: "capacity waterfall", labelW: 176 }),
        el("p", { class: "note", html: `Only <b>${pct(t1.waterfall[2].gpu_hours / c.gpu_hours)}</b> of what was paid for `
          + `was busy <i>and</i> on a job that finished. That is the brief's "83% did not turn into completed work" &mdash; `
          + `it is not the same as 83% being recoverable.` }),
        tableWrap(t1.waterfall, [{ h: "Stage", k: "label", l: 1 }, { h: "GPU-hours", f: (r) => num(r.gpu_hours) }, { h: "USD", f: (r) => usdFull(r.usd) }]),
      ]),
      el("div", {}, [
        el("h3", { text: "By how the job ended" }),
        bars(t1.outcomes, { aria: "spend by outcome", labelW: 120 }),
        el("p", { class: "note", html: `Cancelled work is the second largest slice, and <b>not</b> waste in itself: `
          + `those jobs ran at 34% utilization. Only the idle time before the cancel is recoverable.` }),
        tableWrap(t1.outcomes, [{ h: "Outcome", k: "label", l: 1 }, { h: "Jobs", f: (r) => num(r.jobs) },
          { h: "GPU-hours", f: (r) => num(r.gpu_hours) }, { h: "of it busy", f: (r) => num(r.busy_gpu_hours) },
          { h: "USD", f: (r) => usdFull(r.usd) }]),
      ]),
    ]),
    el("div", { style: "margin-top:18px" }, [
      el("h3", { text: "By how hard the GPUs worked" }),
      bars(t1.util_bands, { aria: "spend by utilization band", labelW: 120 }),
      el("p", { class: "note", html: `The first two rows &mdash; GPUs that averaged under 5% &mdash; are `
        + `${usd(t1.util_bands[0].usd + t1.util_bands[1].usd)} of spend. Tile 2 is about getting that back.` }),
      tableWrap(t1.util_bands, [{ h: "Average utilization", k: "label", l: 1 }, { h: "Jobs", f: (r) => num(r.jobs) },
        { h: "GPU-hours", f: (r) => num(r.gpu_hours) }, { h: "USD", f: (r) => usdFull(r.usd) }]),
    ]),
  );

  /* ---- tile 2: where to cut ---- */
  const acts = d.tile2.actions;
  $("#tile2").append(
    el("span", { class: "tileno", text: "Tile 2" }),
    el("h2", { text: "Where to cut" }),
    el("p", { class: "sub", text: "Three specific actions, ranked by what they return. Each has an owner, a range, and a click-through to the jobs behind it." }),
    intervals(acts),
    el("p", { class: "legend", html: `<span><span class="swatch" style="background:var(--series-1)"></span>point estimate, with low&ndash;high range</span>` }),
    ...acts.map((a, i) => {
      const det = el("details", { class: "action" });
      det.appendChild(el("summary", {}, [
        el("div", { class: "arow" }, [
          el("div", {}, [
            el("h3", { text: `${i + 1}. ${a.title}` }),
            el("p", { class: "meta", text: a.action }),
            el("p", { class: "meta", html: `<span class="tag">owner: ${a.owner}</span> `
              + `<span class="tag">effort: ${a.effort}</span> <span class="tag">confidence: ${a.confidence}</span> `
              + `<span class="tag">${pct(a.share_of_spend)} of capacity</span>` }),
          ]),
          el("div", { style: "text-align:right" }, [
            el("div", { class: "money", text: usd(a.usd) }),
            el("div", { class: "note", html: `${usd(a.low_usd)} &ndash; ${usd(a.high_usd)}<br>${num(a.gpu_hours)} GPU-hours` }),
            el("div", { class: "note", text: "click for the evidence" }),
          ]),
        ]),
      ]));
      const drill = el("div", { class: "drill" });
      drill.append(
        el("p", { class: "risk", html: `<b>If we are wrong:</b> ${a.risk}`
          + (a.risk_usd ? ` Exposure if the pattern does not hold: about <b>${usdFull(a.risk_usd)}</b>.` : "") }),
        el("div", { class: "grid2" }, [
          el("div", {}, [
            el("h3", { text: "How the number moves" }),
            table(a.sensitivity, [{ h: "Assumption", k: "label", l: 1 }, { h: "GPU-hours", f: (r) => num(r.gpu_hours) }, { h: "USD", f: (r) => usdFull(r.usd) }]),
          ]),
          el("div", {}, [
            el("h3", { text: "Where it sits" }),
            table(a.split, [{ h: "Part", k: "label", l: 1 }, { h: "GPU-hours", f: (r) => num(r.gpu_hours) },
              { h: "USD", f: (r) => usdFull(r.gpu_hours * RATE) }]),
          ]),
        ]),
        el("h3", { style: "margin-top:14px", text: "The jobs behind it (largest first)" }),
        el("p", { class: "note", text: a.evidence_note }),
        table(a.drill, [
          { h: "Job id", k: "job", l: 1, mono: 1 }, { h: "Owner", k: "owner", l: 1, mono: 1 },
          { h: "Machine", k: "node", l: 1, mono: 1 }, { h: "GPUs", k: "gpus" },
          { h: "GPU-hours", f: (r) => num(r.gpu_hours) }, { h: "USD", f: (r) => usdFull(r.usd) },
          { h: "Avg util", f: (r) => r.util_avg + "%" }, { h: "Peak util", f: (r) => r.util_peak + "%" },
          { h: "Held for", f: (r) => num(r.hours_held) + " h" }, { h: "Outcome", k: "state", l: 1 },
        ]),
        el("p", { class: "note", style: "margin-top:10px",
          html: `Straight to the detector: <code>${a.api}</code><br>Finding ids: `
            + a.findings.map((x) => `<code>${x.slice(0, 8)}</code>`).join(" ") }),
      );
      det.appendChild(drill);
      det.addEventListener("toggle", () => det.classList.toggle("open", det.open));
      return det;
    }),
    el("p", { class: "note", style: "margin-top:14px", html: `<b>Total, deduplicated: ${usdFull(rec.point_usd)}</b> `
      + `(${usdFull(rec.low_usd)} &ndash; ${usdFull(rec.high_usd)}). ${rec.basis} Each job is counted once, in one `
      + `class only &mdash; summing the detectors' own impact figures instead would claim 157% of the cluster.` }),
  );

  /* ---- tile 3: what it costs if we are wrong ---- */
  $("#tile3").append(
    el("span", { class: "tileno", text: "Tile 3" }),
    el("h2", { text: "What it costs if we are wrong" }),
    el("p", { class: "sub", text: "The four expensive mistakes available in this data. Three of them are things the detection API or its numbers actively suggest." }),
    bars(d.tile3.wrong.filter((w) => w.in_chart !== false)
      .map((w) => ({ label: w.title, usd: w.cost_usd, note: w.verdict })),
      { aria: "cost of each mistake", colors: ["var(--critical)"], labelW: 320 }),
    el("p", { class: "legend", html: `<span><span class="swatch" style="background:var(--critical)"></span>what the mistake costs (capacity destroyed, or work promised that was already useful)</span>` }),
    ...d.tile3.wrong.map((w) => el("div", { class: "wrongcard" }, [
      el("div", { class: "arow" }, [
        el("div", {}, [
          el("h3", { text: w.title }),
          el("p", { class: "note", html: `suggested by <code>${w.source}</code>`
            + (w.claimed_usd ? ` &middot; quotes <b>${usdFull(w.claimed_usd)}</b> ${w.claim_label || ""}` : "") }),
        ]),
        el("div", { style: "text-align:right" }, [
          el("div", { class: "verdict", text: w.verdict }),
          el("div", { class: "money bad", text: usd(w.cost_usd) }),
          el("div", { class: "note", text: "cost of doing it" }),
        ]),
      ]),
      el("p", { class: "meta", text: w.cost_note }),
      w.chart_note ? el("p", { class: "note", text: w.chart_note }) : null,
      el("p", { class: "meta", html: `<b>Why:</b> ${w.why}` }),
      w.causal ? el("div", { class: "meta", style: "border-left:3px solid var(--series-1);padding-left:12px" }, [
        el("div", { html: `<b>POST /v1/causal</b> on <code>${w.causal.finding_id.slice(0, 8)}</code> `
          + `(<code>${w.causal.detector}</code>) answers: &ldquo;${w.causal.root_cause}&rdquo; `
          + `at confidence ${w.causal.confidence}.` }),
        table(w.causal.culprits, [{ h: "Ranked culprit", k: "name", l: 1, mono: 1 },
          { h: "Type", k: "type", l: 1 }, { h: "Score", k: "score" }]),
        el("p", { class: "note", text: "This is the endpoint that collapses a cluster of findings onto the "
          + "one resource underneath them. The recommendation that ranks machines by finding count never "
          + "calls it -- which is exactly how one cause becomes a list of machines to drain." }),
      ]) : null,
      w.rows && w.rows.length ? el("details", {}, [
        el("summary", { class: "note", style: "cursor:pointer", text: "the evidence" }),
        w.id === "drain_top5" ? table(w.rows, [
          { h: "Machine", k: "node", l: 1, mono: 1 }, { h: "Findings", k: "findings" },
          { h: "of which array-task failures", k: "array_task_findings" },
          { h: "Triage verdict", f: (r) => r.verdicts.join(", "), l: 1 },
          { h: "Hardware evidence", k: "hardware_evidence", l: 1 },
          { h: "Jobs served", f: (r) => num(r.jobs) }, { h: "GPU-hours served", f: (r) => num(r.gpu_hours_served) },
        ]) : w.id === "queue_salary" ? table(w.rows, [
          { h: "Way of counting", k: "label", l: 1 }, { h: "Hours", f: (r) => num(r.hours) }, { h: "At $95/h", f: (r) => usdFull(r.usd) },
        ]) : w.id === "drain_incident" ? table(w.rows, [
          { h: "Machine", k: "node", l: 1, mono: 1 }, { h: "Role", k: "role", l: 1 },
        ]) : table(w.rows, [
          { h: "Part of cancelled time", k: "label", l: 1 }, { h: "GPU-hours", f: (r) => num(r.gpu_hours) },
          { h: "USD", f: (r) => usdFull(r.gpu_hours * RATE) },
        ]),
      ]) : null,
    ])),
  );

  /* ---- tile 4: the queue, simulated ---- */
  const sc = d.tile4;
  if (sc) {
    const pol = sc.policies, best = pol[pol.length - 1], nowRow = pol[0];
    $("#tile4").append(
      el("span", { class: "tileno", text: "Tile 4" }),
      el("h2", { text: "Would cutting 20% make researchers wait?" }),
      el("p", { class: "sub", html: `Not if we fix the queue first &mdash; and the queue is not short of hardware. `
        + `We replayed <b>all ${num(sc.jobs_simulated)} startable jobs</b> (of ${num(sc.jobs_total)} in the `
        + `dataset) through a discrete-event simulator at ${sc.gpus} GPUs, with each researcher's own `
        + `concurrency quota in place.` }),
      el("div", { class: "grid2" }, [
        el("div", {}, [
          el("h3", { text: "1. The model, checked against what really happened" }),
          table(sc.validation, [{ h: "", k: "metric", l: 1 },
            { h: "Observed", f: (r) => fmtv(r.observed, r.unit) },
            { h: "Model", f: (r) => fmtv(r.model, r.unit) }]),
          el("p", { class: "note", html: `The model reproduces <b>${pct(sc.fidelity_total)} of the total waiting</b> `
            + `and <b>${pct(sc.fidelity)} of the person-hours</b>. Without the quotas it reproduced 5% and 1%: `
            + `<b>the quota is the constraint</b>, not capacity and not queue order. The rest is work outside `
            + `this published sample, so every saving below is understated.` }),
        ]),
        el("div", {}, [
          el("h3", { text: "2. Why people wait: their own quota" }),
          el("p", { class: "meta", html: `Each researcher is capped at a fixed number of GPUs &mdash; the data `
            + `shows rungs at <b>${sc.caps.ladder.join(" / ")}</b> (${sc.caps.snapped} of ${sc.caps.users} `
            + `owners sit exactly on one). In <b>90%</b> of waits over an hour, the person was already at their `
            + `cap, while a median of <b>287 of 450 GPUs sat free</b>.` }),
          el("p", { class: "meta", html: `So a researcher submits 200 tasks, ${sc.caps.ladder[0]} run, and the `
            + `rest queue behind their own jobs on a two-thirds idle cluster. Reordering the queue cannot fix `
            + `that; only the quota can.` }),
          el("p", { class: "note", html: `Reference run: removing quotas entirely leaves `
            + `<b>${num(sc.no_caps.person_h)} person-hours</b> against ${num(nowRow.person_h)} today &mdash; `
            + `confirming the ceiling is what binds.` }),
        ]),
      ]),
      el("div", { style: "margin-top:18px" }, [
        el("h3", { text: "3. Now vs optimized — person-hours researchers spend waiting" }),
        bars(pol.map((r) => ({ label: r.policy.replace("NOW: ", ""), usd: r.person_h,
                               note: r.delta_pct ? `${(r.delta_pct * 100).toFixed(0)}% vs today` : "today" })),
          { aria: "person-hours waiting by policy", fmt: (v) => num(v) + " h", labelW: 230 }),
        el("p", { class: "legend", html: `<span><span class="swatch" style="background:var(--series-1)"></span>`
          + `person-hours waiting (each researcher's overlapping waits merged, so one person waiting on 200 `
          + `tasks counts once)</span>` }),
        table(pol.concat([sc.no_caps]), [
          { h: "Policy", k: "policy", l: 1 }, { h: "Person-hours", f: (r) => num(r.person_h) },
          { h: "vs today", f: (r) => r.delta_pct ? (r.delta_pct * 100).toFixed(0) + "%" : "—" },
          { h: "Jobs over 4h", f: (r) => num(r.over_4h) }, { h: "p95", f: (r) => r.p95_h + " h" },
          { h: "p99", f: (r) => r.p99_h + " h" },
          { h: "Researcher time at $95/h", f: (r) => usdFull(r.usd) }]),
        el("p", { class: "meta", html: `<b>The fix is worth ${usdFull(Math.abs(best.delta_usd))} of researcher `
          + `time</b> and costs no capacity: it hands out cards that are already idle. The idle timeout from `
          + `tile 2 appears here too &mdash; it returns GPU money <i>and</i> shortens the queue, because an idle `
          + `job holds a slot against its owner's quota.` }),
      ]),
      dial(sc, nowRow),
      el("p", { class: "risk", style: "margin-top:16px",
        html: `<b>If we are wrong:</b> the quotas exist to stop one researcher taking the cluster in a busy `
          + `week, and we simulated the extra jobs as ordinary ones &mdash; with preemption, some of that work `
          + `would be interrupted and resubmitted. The quota values are inferred from each owner's observed `
          + `peak concurrency, not read from Slurm, so the size of the effect could move; the no-quota reference `
          + `run shows the direction does not. And this buys <b>researcher time, not GPU-hours</b>: it does not `
          + `contribute to the 20% cut, it is what makes the cut safe to take.` }),
    );
  }

  /* ---- extras: hardware, triage, queue, clear rules ---- */
  const tri = d.triage.summary;
  $("#extras").append(
    el("h2", { text: "The machine we would actually drain, and the 113 we would not" }),
    el("div", { class: "grid2" }, [
      el("div", {}, [
        el("h3", { text: "One silent hardware fault" }),
        el("p", { class: "meta", html: `<code>${d.hardware.silent_node}</code> ran ${d.hardware.silent_window.join(" to ")} `
          + `and failed 140 of 144 jobs. ${d.hardware.note}` }),
        el("p", { class: "meta", html: `A second unrelated owner hit the same crash on 2026-03-01; `
          + `<b>${d.hardware.jobs_crashed_after_evidence} more jobs crashed</b> before the finding was raised six days later. `
          + `Draining it then would have cost about <b>${usdFull(d.hardware.drain_cost_usd)}</b> of capacity.` }),
        el("p", { class: "meta", html: `Hardware-attributable failures: <b>${d.hardware.point}</b> `
          + `(range ${d.hardware.low}&ndash;${d.hardware.high}) of ${num(d.hardware.failed_jobs_total)} failures `
          + `= <b>${pct(d.hardware.share_of_failed)}</b>. Everything else is user code. `
          + `${d.hardware.scheduler_recorded_jobs} jobs had a run killed by a machine death `
          + `(only ${d.hardware.final_nodefail_jobs} still read NODE_FAIL at the end).` }),
      ]),
      el("div", {}, [
        el("h3", { text: "Why each flagged machine was flagged" }),
        el("p", { class: "meta", text: "rules::node-elevated-failure-rate fired 113 times on 87 machines. It reports a symptom and says nothing about cause, so we triaged every one against like-for-like baselines." }),
        table(Object.entries(tri).map(([k, v]) => ({ cause: k.replace(/_/g, " "), n: v })),
          [{ h: "Cause", k: "cause", l: 1 }, { h: "Findings", k: "n" }]),
        el("p", { class: "note", html: `Only one is hardware. 86 are about people or the work the machine `
          + `received, which is why <b>a finding count is not a drain list</b>.` }),
        el("details", {}, [
          el("summary", { class: "note", style: "cursor:pointer", text: "all 113 verdicts" }),
          table(d.triage.entries, [{ h: "Machine", k: "node", l: 1, mono: 1 }, { h: "Window", k: "window" },
            { h: "Cause", f: (r) => r.cause.replace(/_/g, " "), l: 1 }, { h: "Action", k: "verdict", l: 1 },
            { h: "Reasoning", f: (r) => r.reasoning, l: 1 }]),
        ]),
      ]),
    ]),
    el("h2", { style: "margin-top:22px", text: "Would cutting 20% make researchers wait?" }),
    el("div", { class: "grid2" }, [
      el("div", {}, [
        el("p", { class: "meta", html: `${pct(d.queue.share_starting_within_a_minute)} of jobs start within a minute `
          + `(median wait 0 s). The pain is the tail: the slowest 1% of jobs hold ${pct(d.queue.tail_share_of_hours)} `
          + `of all waiting, and p99 is ${d.queue.p99_h} hours.` }),
        el("p", { class: "meta", html: `Counted per person and only past a 4-hour target, that is `
          + `<b>${num(d.queue.person_hours_past_target)} person-hours</b> across ${d.queue.people_past_target} people. `
          + `People at a keyboard (interactive sessions) waited <b>${d.queue.interactive_hours} hours in four months</b>.` }),
      ]),
      el("div", {}, [
        el("p", { class: "meta", html: `While someone had been waiting over an hour, jobs that never ran a kernel `
          + `held <b>${num(d.queue.idle_gpu_hours_during_contention)} GPU-hours</b> of cards. In `
          + `<b>${pct(d.queue.share_idle_covers_demand)}</b> of those moments the idle cards alone would have `
          + `covered what the waiting jobs asked for.` }),
        el("p", { class: "meta", html: `This sample holds more than 360 of 450 GPUs only `
          + `${pct(d.queue.share_time_over_360_gpus)} of the time, and never once the never-used allocations are `
          + `returned. <b>Reclaim idle GPUs first, then cut</b>, and watch the weekly p95 queue target as the stop signal.` }),
        el("p", { class: "note", text: d.queue.note }),
      ]),
    ]),
    d.clear_rules && d.clear_rules.length ? el("div", { style: "margin-top:18px" }, [
      el("h3", { text: "What we checked and ruled out" }),
      el("p", { class: "meta", html: `<code>rules::gpu-pcie-saturated</code> is armed and has never fired: the PCIe bus `
        + `peaks at 27% of link capacity. <b>Data movement is not what is holding these GPUs back</b>, so "fix the `
        + `data pipeline" is not on the list. Rules reporting CLEAR: `
        + d.clear_rules.map((r) => `<code>${r.id}</code>`).join(" ") }),
    ]) : null,
  );

  /* ---- footer ---- */
  $("#footer").innerHTML = `<b>How to read this.</b> ${d.meta.caveat}<br>`
    + `Sources: ${d.meta.sources.map((s) => `<code>${s}</code>`).join(" &middot; ")}.`
    + ` The detection API was ${d.meta.api_up ? "live when this page was built" : "unreachable when this page was built; figures come from the local tables"}.`
    + ` Full working, case by case, in <code>track-2/ANALYSIS.md</code>; machine-readable numbers in <code>claims.json</code>.`;

  /* (controls are wired once, in controls()) */
}

/* ------------------------------------------------- tile 4: the policy dial */
/* Each setting is a precomputed full replay of every startable job -- the slider
   selects between real simulation runs, it does not interpolate. */
function dial(sc, nowRow) {
  const THRS = [null, 0.5, 0.6, 0.7, 0.8, 0.9];
  const pick = (thr, kill) => sc.grid.find((r) => r.threshold === thr && r.idle_kill === kill);
  let idx = 3, kill = true;                 // opens on our recommendation: 70% + timeout

  const slider = el("input", { type: "range", min: 0, max: THRS.length - 1, step: 1, value: idx,
                               "aria-label": "allocation threshold below which quotas are lifted" });
  const box = el("input", { type: "checkbox", id: "killbox" });
  box.checked = kill;
  const thrLabel = el("span", { class: "mono", style: "color:var(--text-primary)" });
  const out = el("div", { class: "readout" });
  const chart = el("div", { style: "margin-top:14px" });
  const note = el("p", { class: "note" });

  function paint() {
    const thr = THRS[idx];
    const r = pick(thr, kill) || nowRow;
    const today = pick(null, false);
    const saved = today.person_h - r.person_h;
    thrLabel.textContent = thr === null ? "off — quotas always enforced" : `below ${(thr * 100).toFixed(0)}% allocated`;
    out.innerHTML = "";
    out.append(
      el("div", {}, [
        el("div", { class: "big", text: num(r.person_h) + " h" }),
        el("div", { class: "unit", text: "person-hours researchers spend waiting" }),
      ]),
      el("div", {}, [
        el("div", { class: "delta " + (saved > 0 ? "ok" : saved < 0 ? "bad" : ""),
                    text: saved === 0 ? "no change" : `${saved > 0 ? "−" : "+"}${pct(Math.abs(saved) / today.person_h)} vs today` }),
        el("div", { class: "unit", html: `${saved >= 0 ? "saves" : "costs"} <b>${usdFull(Math.abs(saved) * sc.usd_per_engineer_hour)}</b> of researcher time` }),
      ]),
      el("div", {}, [el("div", { class: "delta", text: num(r.over_4h) }), el("div", { class: "unit", text: "jobs still wait over 4 h" })]),
      el("div", {}, [el("div", { class: "delta", text: r.p95_h + " h" }), el("div", { class: "unit", text: "p95 wait" })]),
      el("div", {}, [el("div", { class: "delta", text: r.p99_h + " h" }), el("div", { class: "unit", text: "p99 wait" })]),
    );
    chart.innerHTML = "";
    chart.appendChild(bars([
      { label: "Today", usd: today.person_h, note: "quotas always enforced" },
      { label: "This setting", usd: r.person_h, note: thrLabel.textContent + (kill ? ", with the idle timeout" : "") },
      { label: "No quotas at all (reference)", usd: sc.no_caps.person_h, dim: true, note: "what removing the ceiling entirely would give" },
    ], { aria: "person-hours waiting under the chosen policy", fmt: (v) => num(v) + " h", labelW: 250 }));
    note.innerHTML = thr !== null && thr >= 0.8
      ? `Above 80% the curve flattens and wobbles &mdash; ${num(pick(0.8, kill).person_h)} h at 80% against `
        + `${num(pick(0.9, kill).person_h)} h at 90% &mdash; because more jobs start early and then compete with `
        + `each other. <b>70% is the setting we would ship</b>: a third of the cluster stays governed by quota `
        + `for genuinely busy hours.`
      : `<b>70% with the idle timeout is the setting we would ship.</b> Lower thresholds leave researchers `
        + `waiting; higher ones leave the quota with almost nothing to do, which is a fairness decision rather `
        + `than a technical one.`;
  }

  slider.addEventListener("input", () => { idx = +slider.value; paint(); });
  box.addEventListener("change", () => { kill = box.checked; paint(); });
  paint();

  return el("div", { style: "margin-top:18px" }, [
    el("h3", { text: "4. Try the fix" }),
    el("p", { class: "meta", text: "Let a researcher exceed their own quota while the cluster is quiet. "
      + "Those extra jobs would be preemptible, so the quota reasserts itself the moment the machine gets busy." }),
    el("div", { class: "dial" }, [
      el("div", { class: "dialrow" }, [
        el("label", {}, [el("span", { text: "Lift quotas:" }), slider, thrLabel]),
        el("label", { for: "killbox" }, [box, el("span", { text: "also end allocations idle for 1 h" })]),
      ]),
      out,
      chart,
      note,
    ]),
    el("p", { class: "note", html: `Every setting on that slider is a <b>full replay of all `
      + `${num(sc.jobs_simulated)} startable jobs</b> at ${sc.gpus} GPUs, computed when this page was built `
      + `(12 simulations). The slider selects between real runs &mdash; it does not interpolate.` }),
  ]);
}

function controls() {
  const themeBtn = $("#theme");
  const startDark = matchMedia("(prefers-color-scheme: dark)").matches;
  let dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : startDark;
  const paint = () => { document.documentElement.dataset.theme = dark ? "dark" : "light"; themeBtn.textContent = dark ? "Light" : "Dark"; };
  paint();
  themeBtn.onclick = () => { dark = !dark; paint(); };

  let shown = false;
  $("#tables").onclick = () => {
    shown = !shown;
    document.querySelectorAll(".tablebox").forEach((b) => { b.style.display = shown ? "block" : "none"; });
    $("#tables").textContent = shown ? "Hide tables" : "Show all tables";
  };
}
