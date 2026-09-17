/* GPU spend dashboard.
   UI: Shruti Doshi's design -- the tabbed shell, KPI rows, spend wheel and row
   components are hers (see "Shruti's dashboard/"); the wheel code below is taken
   from her app.js unchanged. Data: dashboard/build.py -- one class per job, live
   POST /v1/causal, the price-book override through the /api proxy, and the
   scheduler simulation behind tab 4. */

const $ = (id) => document.getElementById(id);
const usd = (n) => {
  if (n === null || n === undefined) return "--";
  const a = Math.abs(n);
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${Math.round(n / 1e3).toLocaleString()}K`;
  return `$${Math.round(n).toLocaleString()}`;
};
const usdFull = (n) => "$" + Math.round(n).toLocaleString("en-US");
const num = (n) => (n === null || n === undefined ? "--" : Math.round(n).toLocaleString());
const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`;
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
};

/* One colour per bucket, so the eye can follow a bucket across the tabs. */
const HUE = {
  never_used: "#d29922", barely_used: "#bc8cff", cpu_work: "#58a6ff",
  idle_card: "#39c5cf", killed_by_clock: "#f85149", productive: "#3fb950",
};

/* ------------------------------------------------- price: one rate, one scale */
/* Every GPU figure is priced at the price book's rate. Changing the rate rescales
   those -- blocks tagged priced_in:"engineer" are salary and are left alone -- and
   asks the API to re-price its own waterfall, which comes back tagged +custom. */
let RAW = null, D = null, BASE = 2.5, RATE = 2.5;
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
  const input = $("rate");
  input.value = RATE.toFixed(2);
  const apply = () => {
    const v = parseFloat(input.value);
    if (!(v > 0) || v === RATE) return;
    RATE = v;
    draw();
  };
  input.addEventListener("change", apply);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") apply(); });
  wireTabs();
  draw();
}).catch((e) => {
  document.querySelector("main").prepend(el("div", "callout warnbox",
    `<strong>No data.json.</strong> It is built by <code>dashboard/build.py</code> when the
     container starts (about 90 seconds, including the scheduler simulation). (${e})`));
});

function draw() {
  D = scale(RAW);
  renderHeader(); renderTile1(); renderTile2(); renderTile3(); renderTile4(); renderTile5();
  priceCheck();
}

/* ----------------------------------------------------------------------- tabs */
const TILES = ["tile1", "tile2", "tile3", "tile4", "tile5"];
function toTop() {
  const m = document.querySelector("main");
  if (m) m.scrollTop = 0;
  window.scrollTo({ top: 0 });
}
function showTile(id) {
  document.querySelectorAll(".donut-wrap").forEach((w) => w._hideWheelGuide?.());
  [...$("tabs").children].forEach((t) => {
    const on = t.dataset.tile === id;
    t.setAttribute("aria-selected", on ? "true" : "false");
    const panel = $(t.dataset.tile);
    if (on) panel.removeAttribute("hidden"); else panel.setAttribute("hidden", "");
  });
  if (location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
  toTop();
}
function wireTabs() {
  [...$("tabs").children].forEach((t) => t.addEventListener("click", () => showTile(t.dataset.tile)));
  const initial = location.hash.replace("#", "");
  showTile(TILES.includes(initial) ? initial : "tile1");
  // a pasted or edited link to a tab should open that tab
  addEventListener("hashchange", () => {
    const h = location.hash.replace("#", "");
    if (TILES.includes(h)) showTile(h);
  });
}

/* --------------------------------------------------------------------- header */
function renderHeader() {
  const m = D.meta, c = m.cluster;
  $("title").textContent = "Where to cut GPU spend, and what not to touch";
  $("subtitle").innerHTML = `${c.nodes} machines &middot; ${num(c.nodes * c.gpus_per_node)} V100 GPUs &middot; `
    + `${num(c.jobs)} jobs from ${c.users} researchers &middot; ${c.window_days} days &middot; `
    + `$${RATE.toFixed(2)}/GPU-hour `
    + (RATE === BASE ? `(price book ${m.price_book.version})` : `(<b>${m.price_book.version}+custom</b>, book rate $${BASE.toFixed(2)})`);
  $("footer").innerHTML = `A four-month <b>sample</b> of MIT SuperCloud, not the whole cluster; the storage incident is synthetic, `
    + `everything else is real telemetry. <span id="pricetag"></span>`;
}
function renderKpis(box, kpis) {
  box.innerHTML = "";
  kpis.forEach((k) => box.append(el("div", "kpi",
    `<strong>${k.value}</strong><span class="kpi-label">${k.label}</span><span class="kpi-sub">${k.sub}</span>`)));
}

/* Ask the API to re-price its own waterfall at the current rate. */
function priceCheck() {
  const box = $("pricetag");
  box.textContent = `asking the API to re-price at $${RATE.toFixed(2)}/GPU-hour...`;
  fetch(`/api/v1/efficiency/summary?usd_per_gpu_hour=${RATE}`).then((r) => r.json()).then((j) => {
    const m = j.monetized || {};
    box.innerHTML = `Live cross-check: <code>GET /v1/efficiency/summary?usd_per_gpu_hour=${RATE}</code> returns `
      + `<b>${usdFull(m.amount || 0)}</b>, priced as <b>${m.price_book_version || "?"}</b>.`;
  }).catch(() => { box.textContent = `API not reachable from the page; figures are priced locally at $${RATE.toFixed(2)}.`; });
}

function table(rows, cols) {
  if (!rows || !rows.length) return "";
  return `<table><thead><tr>${cols.map((c) => `<th class="${c.l ? "l" : ""}">${c.h}</th>`).join("")}</tr></thead><tbody>`
    + rows.map((r) => `<tr>${cols.map((c) =>
        `<td class="${c.l ? "l " : ""}${c.mono ? "mono " : ""}${c.wrap ? "wrap" : ""}">${c.f ? c.f(r) : (r[c.k] ?? "")}</td>`).join("")}</tr>`).join("")
    + `</tbody></table>`;
}

/* ============================================ the spend wheel (Shruti's code) */
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function polar(cx, cy, rad, t) {
  const a = t * 2 * Math.PI - Math.PI / 2;
  return [cx + rad * Math.cos(a), cy + rad * Math.sin(a)];
}

function ringSlice(cx, cy, r0, r1, t0, t1) {
  const span = t1 - t0;
  if (span <= 0) return "";
  const large = span > 0.5 ? 1 : 0;
  const [x0, y0] = polar(cx, cy, r1, t0);
  const [x1, y1] = polar(cx, cy, r1, t1);
  const [x2, y2] = polar(cx, cy, r0, t1);
  const [x3, y3] = polar(cx, cy, r0, t0);
  const n = (v) => v.toFixed(2);
  return `M${n(x0)} ${n(y0)} A${r1} ${r1} 0 ${large} 1 ${n(x1)} ${n(y1)}` +
    `L${n(x2)} ${n(y2)} A${r0} ${r0} 0 ${large} 0 ${n(x3)} ${n(y3)} Z`;
}

function svgToWrap(svg, wrap, x, y) {
  const wr = wrap.getBoundingClientRect();
  const sr = svg.getBoundingClientRect();
  const scale = Math.min(sr.width / 280, sr.height / 280);
  return {
    x: sr.left + (sr.width - 280 * scale) / 2 + x * scale - wr.left,
    y: sr.top + (sr.height - 280 * scale) / 2 + y * scale - wr.top,
  };
}

function placeTip(wrap, tip, x, y) {
  tip.hidden = false;
  tip.style.visibility = "hidden";
  const pad = 8;
  const wr = wrap.getBoundingClientRect();
  const tw = tip.offsetWidth;
  const th = tip.offsetHeight;
  const minL = wr.left + pad;
  const maxL = wr.right - tw - pad;
  const minT = wr.top + pad;
  const maxT = wr.bottom - th - pad;
  let left = wr.left + x + 14;
  let top = wr.top + y - th - 10;
  if (left > Math.max(minL, maxL)) left = wr.left + x - tw - 14;
  if (top < minT) top = wr.top + y + 14;
  left = Math.min(Math.max(left, minL), Math.max(minL, maxL));
  top = Math.min(Math.max(top, minT), Math.max(minT, maxT));
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
  tip.style.visibility = "";
}

function drawWheel(svg, segments, centreLines) {
  const cx = 140, cy = 140, r = 96, sw = 38;
  const C = 2 * Math.PI * r;
  const r0 = r - sw / 2 - 2, r1 = r + sw / 2 + 2;
  // Namespaced so two wheels on one page cannot share a <pattern> definition.
  const hatch = `hatch-${svg.id || `wheel${++wheelCount}`}`;
  let acc = 0;
  let out =
    `<defs><pattern id="${hatch}" width="6" height="6" patternTransform="rotate(45)"
       patternUnits="userSpaceOnUse">
       <rect width="6" height="6" fill="#20272f"/>
       <line x1="0" y1="0" x2="0" y2="6" stroke="#38424e" stroke-width="2.5"/>
     </pattern></defs>`;

  const arc = (len, paint) => {
    if (len <= 0) return "";
    const s = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${paint}"
      stroke-width="${sw}" stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}"
      stroke-dashoffset="${(-acc).toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"
      pointer-events="none"/>`;
    acc += len;
    return s;
  };

  const meta = {};
  let t = 0;
  segments.forEach((s) => {
    const kept = s.kept || 0;
    const cut = s.cut || 0;
    const t1 = t + kept + cut;
    const d = ringSlice(cx, cy, r0, r1, t, t1);
    const label = s.tip ? `${s.tip.name}. ${s.tip.plain}` : s.key;
    out += `<g class="wheel-slice" data-key="${s.key}" role="img" aria-label="${esc(label)}">`;
    out += arc(kept * C, HUE[s.key]);
    out += arc(cut * C, `url(#${hatch})`);
    if (d) out += `<path class="wheel-hit" d="${d}" fill="transparent"/>`;
    out += `</g>`;
    meta[s.key] = { tip: s.tip, t0: t, t1 };
    t = t1;
  });

  /* Each line reserves a box of its own size, so a big line following a small one
     cannot climb into it. Baselines sit 0.82 of the way down their box. */
  const boxH = (l) => (l.gap || 0) + l.size * 1.18;
  let top = cy - centreLines.reduce((s, l) => s + boxH(l), 0) / 2;
  centreLines.forEach((l) => {
    top += l.gap || 0;
    out += `<text x="${cx}" y="${(top + l.size * 0.82).toFixed(1)}" fill="${l.colour}"
      font-size="${l.size}" font-weight="${l.weight || 400}" text-anchor="middle"
      pointer-events="none"${
      l.strike ? ' text-decoration="line-through"' : ""}>${l.text}</text>`;
    top += l.size * 1.18;
  });
  svg.innerHTML = out;
  svg.setAttribute("aria-label", "Spend wheel. Hover a slice to see what it is.");
  wireWheel(svg, meta);
}

function wireWheel(svg, meta) {
  const wrap = svg.closest(".donut-wrap");
  if (!wrap) return;
  let tip = wrap.querySelector(".wheel-tip");
  if (!tip) {
    tip = el("div", "wheel-tip");
    tip.hidden = true;
    wrap.append(tip);
  }

  const hide = () => {
    wrap.classList.remove("is-guiding");
    svg.querySelectorAll(".wheel-slice.is-hot").forEach((g) => g.classList.remove("is-hot"));
    svg.closest(".tile")?.querySelectorAll(".row.is-hot")
      .forEach((r) => r.classList.remove("is-hot"));
    tip.hidden = true;
  };

  const show = (key) => {
    const m = meta[key];
    if (!m || !m.tip) return;
    wrap.classList.add("is-guiding");
    svg.querySelectorAll(".wheel-slice").forEach((g) => {
      g.classList.toggle("is-hot", g.dataset.key === key);
    });
    svg.closest(".tile")?.querySelectorAll(".row").forEach((r) => {
      r.classList.toggle("is-hot", r.dataset.key === key);
    });
    const t = m.tip;
    tip.innerHTML =
      `<span class="wheel-tip-name"><i class="dot" style="background:${HUE[key]}"></i>${esc(t.name)}</span>` +
      `<span class="wheel-tip-plain">${esc(t.plain)}</span>` +
      `<span class="wheel-tip-figs">${t.figs}</span>` +
      (t.sub ? `<span class="wheel-tip-sub">${esc(t.sub)}</span>` : "");
    const mid = (m.t0 + m.t1) / 2;
    const [sx, sy] = polar(140, 140, 128, mid);
    const at = svgToWrap(svg, wrap, sx, sy);
    placeTip(wrap, tip, at.x, at.y);
  };

  svg.querySelectorAll(".wheel-slice").forEach((g) => {
    g.addEventListener("pointerenter", () => show(g.dataset.key));
    g.addEventListener("pointerleave", hide);
  });
  wrap._showWheelGuide = show;
  wrap._hideWheelGuide = hide;
}


/* =================================================================== TAB 1 == */
function spineTip(b, figs, sub) { return { name: b.name, plain: b.plain, figs, sub }; }

function renderTile1() {
  const t = D.tile1, c = D.meta.cluster;
  const never = D.spine.filter((b) => ["never_used", "cpu_work"].includes(b.key)).reduce((s, b) => s + b.usd, 0);
  renderKpis($("t1-kpis"), [
    { value: usd(c.usd), label: "spent on GPUs in four months", sub: `${num(c.gpu_hours)} GPU-hours across ${c.nodes} machines` },
    { value: pct(t.waterfall[2].gpu_hours / c.gpu_hours, 0), label: "was busy on a job that finished",
      sub: "the brief's 83% that didn't is not the same as 83% recoverable" },
    { value: usd(never), label: "held GPUs that never ran a calculation", sub: "average and peak utilisation both exactly zero" },
  ]);
  drawWheel($("c-donut"), D.spine.map((b) => ({
    key: b.key, kept: b.share_of_bill,
    tip: spineTip(b, `${usd(b.usd)} · ${pct(b.share_of_bill, 0)} of the bill`,
      `${num(b.jobs)} jobs · the card was computing ${b.busy_pct}% of the time`),
  })), [
    { text: usd(c.usd), size: 30, colour: "#e6edf3", weight: 600 },
    { text: "total GPU bill", size: 11.5, colour: "#6e7d8c", gap: 4 },
  ]);
  bucketRows($("t1-buckets"), (b) => ({
    sub: `${num(b.jobs)} jobs &middot; the card was computing ${b.busy_pct}% of the time`,
    figs: `<strong>${usd(b.usd)}</strong><span class="row-note">${pct(b.share_of_bill, 0)} of the bill</span>`,
  }));
}

function bucketRows(box, figures, onClick) {
  box.innerHTML = "";
  const wrap = box.closest(".two-col")?.querySelector(".donut-wrap");
  D.spine.forEach((b) => {
    const row = el("div", "row");
    row.dataset.key = b.key;
    row.style.borderLeftColor = HUE[b.key];
    const f = figures(b);
    row.innerHTML = `<div class="row-main"><span class="row-title">${b.name}</span>
      <span class="row-sub">${f.sub}</span></div><div class="row-figs">${f.figs}</div>`;
    if (wrap) {
      row.addEventListener("pointerenter", () => wrap._showWheelGuide?.(b.key));
      row.addEventListener("pointerleave", () => wrap._hideWheelGuide?.());
    }
    if (onClick && b.action_id) { row.classList.add("clickable"); row.addEventListener("click", () => onClick(b, row)); }
    box.append(row);
  });
}

/* =================================================================== TAB 2 == */
function renderTile2() {
  const rec = D.tile2.recoverable, c = D.meta.cluster;
  const met = rec.point_usd >= rec.target_usd;
  renderKpis($("t2-kpis"), [
    { value: usd(rec.point_usd), label: "recoverable, each job counted once", sub: `range ${usd(rec.low_usd)} – ${usd(rec.high_usd)} · ${pct(rec.point / c.gpu_hours, 0)} of capacity` },
    { value: met ? "target met" : "target missed", label: `the 20% target is ${usd(rec.target_usd)}`, sub: "met at the point estimate; the low end alone does not reach it" },
    { value: "1", label: "machine to drain", sub: "not the 121 the findings suggest, not the 5 the API recommends" },
  ]);
  const cutUsd = D.spine.reduce((s, b) => s + b.cut_usd, 0);
  drawWheel($("t2-wheel"), D.spine.map((b) => ({
    key: b.key, kept: b.share_of_bill - b.cut_share_of_bill, cut: b.cut_share_of_bill,
    tip: spineTip(b, b.cut_usd > 0 ? `&minus;${usd(b.cut_usd)} hatched cut · ${usd(b.usd - b.cut_usd)} stays`
      : `${usd(b.usd)} stays · nothing hatched`, b.action),
  })), [
    { text: `was ${usd(c.usd)}`, size: 12, colour: "#6e7d8c", strike: true },
    { text: usd(c.usd - cutUsd), size: 30, colour: "#3fb950", weight: 600, gap: 4 },
    { text: `&minus;${usd(cutUsd)} (${pct(cutUsd / c.usd, 0)})`, size: 12.5, colour: "#e6edf3", gap: 2 },
  ]);
  bucketRows($("t2-actions"), (b) => ({
    sub: `${b.action} <i>${b.owner === "--" ? "" : b.owner}</i>`,
    figs: b.cut_gpu_hours > 0
      ? `<strong class="cut-val">&minus;${usd(b.cut_usd)}</strong><span class="row-note ${b.confidence}">${b.confidence} confidence</span>`
      : `<strong class="none-val">no cut</strong><span class="row-note">${usd(b.usd)} stays</span>`,
  }), (b, row) => {
    const a = D.tile2.actions.find((x) => x.id === b.action_id), box = $("t2-drill");
    const same = box.dataset.open === b.key && !box.hidden;
    document.querySelectorAll("#t2-actions .row").forEach((r) => r.classList.remove("open"));
    if (same || !a) { box.hidden = true; $("tile2").classList.remove("long"); return; }
    // her tabs are sized to one screen; an open drill-down lets this one grow and scroll
    $("tile2").classList.add("long");
    row.classList.add("open"); box.dataset.open = b.key; box.hidden = false;
    box.innerHTML = `<h3>${a.title} &middot; ${usd(a.usd)} (${usd(a.low_usd)} – ${usd(a.high_usd)}) &middot; owner: ${a.owner}</h3>
      <p class="meta">${a.action}</p>
      <p class="meta"><b>If we are wrong:</b> ${a.risk}${a.risk_usd ? ` Exposure: about <b>${usdFull(a.risk_usd)}</b>.` : ""}</p>
      <div class="grid2"><div><b>How the number moves</b>${table(a.sensitivity, [{ h: "Assumption", k: "label", l: 1 },
        { h: "GPU-hours", f: (r) => num(r.gpu_hours) }, { h: "USD", f: (r) => usdFull(r.usd) }])}</div>
      <div><b>Where it sits</b>${table(a.split, [{ h: "Part", k: "label", l: 1 }, { h: "GPU-hours", f: (r) => num(r.gpu_hours) },
        { h: "USD", f: (r) => usdFull(r.gpu_hours * RATE) }])}</div></div>
      <b>The jobs behind it, largest first</b><p class="note">${a.evidence_note}</p>
      ${table(a.drill, [{ h: "Job id", k: "job", l: 1, mono: 1 }, { h: "Owner", k: "owner", l: 1, mono: 1 },
        { h: "Machine", k: "node", l: 1, mono: 1 }, { h: "GPUs", k: "gpus" }, { h: "GPU-hours", f: (r) => num(r.gpu_hours) },
        { h: "USD", f: (r) => usdFull(r.usd) }, { h: "Avg util", f: (r) => r.util_avg + "%" }, { h: "Peak", f: (r) => r.util_peak + "%" },
        { h: "Held", f: (r) => num(r.hours_held) + " h" }, { h: "Outcome", k: "state", l: 1 }])}
      <p class="note">Straight to the detector: <code>${a.api}</code> &middot; finding ids ${a.findings.map((x) => `<code>${x.slice(0, 8)}</code>`).join(" ")}</p>`;
    box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

/* =================================================================== TAB 3 == */
function renderTile3() {
  const w = D.tile3.wrong;
  renderKpis($("t3-kpis"), [
    { value: usd(w[0].cost_usd), label: "a quarter, to drain the API's five machines", sub: `it claims ${usd(w[0].claimed_usd)} saved; it saves nothing` },
    { value: "0", label: "machines to drain for the storage incident", sub: "121 findings, one shared volume" },
    { value: "6.3×", label: "the GPU bill: the API's price for queue waiting", sub: "$9.33M of 'salary' that nobody is paid to spend" },
  ]);
  const LEVEL = { drain_top5: "risky", drain_incident: "risky", cancelled_as_waste: "not a saving", queue_salary: "not a saving" };
  const box = $("t3-risks");
  box.innerHTML = "";
  w.forEach((r) => {
    const lv = LEVEL[r.id] || "risky";
    const row = el("div", `row clickable level-${lv.replace(/ /g, "-")}`);
    row.innerHTML = `<div class="row-main"><span class="row-title">${r.title}</span>
        <span class="row-sub">${r.cost_note}</span></div>
      <div class="row-figs"><strong>${usd(r.cost_usd)}</strong><span class="level">${r.verdict.toLowerCase()}</span></div>`;
    const detail = el("div", "detail");
    detail.hidden = true;
    detail.innerHTML = `<p>Suggested by <code>${r.source}</code>${r.claimed_usd ? ` &middot; quotes <b>${usdFull(r.claimed_usd)}</b> ${r.claim_label || ""}` : ""}</p>
      <p><b>Why:</b> ${r.why}</p>`
      + (r.causal ? `<p><b>POST /v1/causal</b> on <code>${r.causal.finding_id.slice(0, 8)}</code> (<code>${r.causal.detector}</code>) answers, live:
          &ldquo;${r.causal.root_cause}&rdquo; at confidence ${r.causal.confidence}.</p>
          ${table(r.causal.culprits, [{ h: "Ranked culprit", k: "name", l: 1, mono: 1 }, { h: "Type", k: "type", l: 1 }, { h: "Score", k: "score" }])}
          <p class="note">This endpoint collapses a cluster of findings onto the one resource underneath them. The recommendation
          that ranks machines by finding count never calls it.</p>` : "")
      + (r.id === "drain_top5" ? table(r.rows, [{ h: "Machine", k: "node", l: 1, mono: 1 }, { h: "Findings", k: "findings" },
          { h: "array-task failures", k: "array_task_findings" }, { h: "Triage verdict", f: (x) => x.verdicts.join(", "), l: 1 },
          { h: "GPU-hours served", f: (x) => num(x.gpu_hours_served) }])
        : r.id === "queue_salary" ? table(r.rows, [{ h: "Way of counting", k: "label", l: 1 }, { h: "Hours", f: (x) => num(x.hours) }, { h: "At $95/h", f: (x) => usdFull(x.usd) }])
        : r.id === "cancelled_as_waste" ? table(r.rows, [{ h: "Part of cancelled time", k: "label", l: 1 }, { h: "GPU-hours", f: (x) => num(x.gpu_hours) }, { h: "USD", f: (x) => usdFull(x.gpu_hours * RATE) }])
        : "");
    row.append(detail);
    row.addEventListener("click", (e) => {
      if (e.target.closest(".detail")) return;
      detail.hidden = !detail.hidden; row.classList.toggle("open", !detail.hidden);
    });
    box.append(row);
  });
}

/* =================================================================== TAB 4 == */
function hbars(rows, max) {
  return rows.map((r) => `<div class="hbar"><span>${r.label}</span>
    <span class="track"><span class="fill ${r.dim ? "dim" : ""}" style="display:block;width:${Math.max(0.6, 100 * r.v / max)}%"></span></span>
    <span class="v">${num(r.v)} h</span></div>`).join("");
}

function renderTile4() {
  const sc = D.tile4, body = $("t4-body");
  if (!sc) { $("t4-kpis").innerHTML = ""; body.innerHTML = `<p class="meta">The scheduler simulation was skipped (<code>DASH_SIM=0</code>).</p>`; return; }
  const today = sc.grid.find((r) => r.threshold === null && !r.idle_kill);
  const best = sc.grid.find((r) => r.threshold === 0.7 && r.idle_kill);
  renderKpis($("t4-kpis"), [
    { value: "90%", label: "of long waits: the person was at their own quota", sub: `quota rungs at ${sc.caps.ladder.join(" / ")} GPUs` },
    { value: "287 of 450", label: "GPUs sat free while they waited (median)", sub: "the queue is a quota problem, not a capacity one" },
    { value: `${num(today.person_h - best.person_h)} h`, label: "of researcher waiting removed by the fix", sub: `${pct(1 - best.person_h / today.person_h, 0)} of the modelled waiting, at no capacity cost` },
  ]);
  body.innerHTML = `<div class="grid2">
      <div class="panel"><h3>The model, checked against what really happened</h3>
        ${table(sc.validation, [{ h: "", k: "metric", l: 1 }, { h: "Observed", f: (r) => fmtv(r.observed, r.unit) }, { h: "Model", f: (r) => fmtv(r.model, r.unit) }])}
        <p class="note">We replayed all ${num(sc.jobs_simulated)} startable jobs at ${sc.gpus} GPUs with each researcher's own quota in place.
        The model reproduces <b>${pct(sc.fidelity_total, 0)} of total waiting</b> and ${pct(sc.fidelity, 0)} of person-hours; without quotas it
        reproduced 5% and 1%. <b>The quota is the constraint.</b> The rest is work outside this published sample, so savings here are understated.</p></div>
      <div class="panel"><h3>Try the fix</h3>
        <p class="note">Let a researcher exceed their quota while the cluster is quiet (the extra jobs preemptible). Every setting is a
        full replay, precomputed when this page was built &mdash; the slider selects between 12 real runs, it does not interpolate.</p>
        <div id="dial"></div></div></div>
    <div class="panel" style="margin-top:14px"><h3>Safer than a reactive quota: a credits pool <span class="fig-hint">case 10 &middot; try it</span></h3>
      <p class="note">The elastic rule above cannot know who is about to come back, and 136 of the jobs it starts early run over 24 hours.
      A <b>credits pool</b> bounds the risk instead: a researcher who has been away for 4 hours lends their unused quota &mdash; their own
      quota is never reduced &mdash; and a waiting job may borrow only if it is expected to finish inside the loan window.</p>
      <div id="pool"></div>
      <p class="note">We also tested <b>forecasting each researcher's quota</b> from two weeks of their own demand. It fails: demand is bursty,
      the forecast is 2&times; too low in 21% of active weeks, and waiting rises 1,316%. Recommended order: the idle timeout, then the pool,
      and the elastic rule only once preemption exists.</p></div>
    <p class="note"><b>Hours are the honest unit here.</b> The dollar figure prices waiting at $${sc.usd_per_engineer_hour}/engineer-hour and so assumes the
    wait fully blocks the person &mdash; the assumption we argue against in <code>/v1/queue/latency</code> (tab 3). It is an upper bound and is
    <b>not added to the GPU savings</b>: that is cash you stop spending, this is throughput you get back. Quotas are inferred from each
    owner's observed peak concurrency, not read from Slurm.</p>`;
  dial(sc, today);
  poolDial();
}
const fmtv = (v, unit) => unit === "jobs" ? num(v) : (Math.abs(v) < 100 ? v.toFixed(2) : num(v)) + " " + unit;

function dial(sc, today) {
  const THRS = [null, 0.5, 0.6, 0.7, 0.8, 0.9];
  const pick = (thr, kill) => sc.grid.find((r) => r.threshold === thr && r.idle_kill === kill);
  let idx = 3, kill = true;
  const host = $("dial");
  host.innerHTML = `<div class="dial"><div class="dialrow">
      <label>Lift quotas: <input id="d-thr" type="range" min="0" max="5" step="1" value="3"> <span id="d-lab" class="mono"></span></label>
      <label><input id="d-kill" type="checkbox" checked> also end allocations idle for 1 h</label></div>
    <div class="readout" id="d-out"></div><div id="d-bars"></div><p class="note" id="d-note"></p></div>`;
  const paint = () => {
    const thr = THRS[idx], r = pick(thr, kill), saved = today.person_h - r.person_h;
    $("d-lab").textContent = thr === null ? "off — quotas always enforced" : `below ${(thr * 100).toFixed(0)}% allocated`;
    $("d-out").innerHTML = `<div><div class="big">${num(r.person_h)} h</div><div class="unit">person-hours researchers spend waiting</div></div>
      <div><div class="delta ${saved > 0 ? "okc" : saved < 0 ? "badc" : ""}">${saved === 0 ? "no change" : `${saved > 0 ? "−" : "+"}${pct(Math.abs(saved) / today.person_h, 0)} vs today`}</div>
        <div class="unit">worth up to <b>${usdFull(Math.abs(saved) * sc.usd_per_engineer_hour)}</b> if that waiting fully blocks the researcher</div></div>
      <div><div class="delta">${num(r.over_4h)}</div><div class="unit">jobs still wait over 4 h</div></div>
      <div><div class="delta">${r.p95_h} h / ${r.p99_h} h</div><div class="unit">p95 / p99 wait</div></div>`;
    $("d-bars").innerHTML = hbars([{ label: "Today", v: today.person_h }, { label: "This setting", v: r.person_h },
      { label: "No quotas at all (reference)", v: sc.no_caps.person_h, dim: true }], today.person_h);
    $("d-note").innerHTML = thr !== null && thr >= 0.8
      ? `Above 80% the curve flattens and wobbles (${num(pick(0.8, kill).person_h)} h at 80%, ${num(pick(0.9, kill).person_h)} h at 90%): more jobs start early and compete. <b>70% is the setting we would ship.</b>`
      : `<b>70% with the idle timeout is the setting we would ship</b>: a third of the cluster stays governed by quota for genuinely busy hours.`;
  };
  $("d-thr").addEventListener("input", (e) => { idx = +e.target.value; paint(); });
  $("d-kill").addEventListener("change", (e) => { kill = e.target.checked; paint(); });
  paint();
}

/* The credits pool. Every setting is a full replay of all startable jobs, computed
   by analysis/case10_grid.py (each takes ~45 s, so they are precomputed rather than
   run at page build). The control selects between real runs. */
function poolDial() {
  const P = D.pool, host = $("pool");
  if (!host) return;
  if (!P) { host.innerHTML = `<p class="meta">Pool grid not built: run <code>PYTHONPATH=analysis python3 analysis/case10_grid.py</code>.</p>`; return; }
  const W = P.windows, base = P.rows.find((r) => r.kind === "base" && !r.idle_kill);
  const find = (w, gate, kill) => P.rows.find((r) => r.kind === "pool" && r.window_h === w && r.gate === gate && r.idle_kill === kill);
  let idx = W.indexOf(P.mean_job_h); if (idx < 0) idx = 2;
  let gate = "history", kill = false;
  host.innerHTML = `<div class="dial"><div class="dialrow">
      <label>Loan window: <input id="p-win" type="range" min="0" max="${W.length - 1}" step="1" value="${idx}"> <span id="p-lab" class="mono"></span></label>
      <label><input type="radio" name="p-gate" value="history" checked> borrow if <b>predicted</b> runtime fits</label>
      <label><input type="radio" name="p-gate" value="limit"> borrow if <b>requested</b> time limit fits</label>
      <label><input id="p-kill" type="checkbox"> also end allocations idle for 1 h</label></div>
    <div class="readout" id="p-out"></div><div id="p-bars"></div><p class="note" id="p-note"></p></div>`;
  const paint = () => {
    const w = W[idx];
    const killBox = $("p-kill");
    killBox.disabled = gate === "limit";            // that combination was not simulated
    const r = find(w, gate, gate === "limit" ? false : kill) || base;
    const saved = base.person_h - r.person_h;
    const overShare = r.borrowed_gpu_h ? r.overrun_gpu_h / r.borrowed_gpu_h : 0;
    $("p-lab").textContent = `${w} h` + (w === P.mean_job_h ? " — the mean job length" : "");
    $("p-out").innerHTML = `<div><div class="big">${num(r.person_h)} h</div><div class="unit">person-hours researchers spend waiting</div></div>
      <div><div class="delta ${saved > 0.5 ? "okc" : ""}">${Math.abs(saved) < 0.5 ? "no change" : `−${pct(saved / base.person_h, 0)} vs today`}</div>
        <div class="unit">worth up to <b>${usdFull(Math.max(saved, 0) * P.usd_per_engineer_hour)}</b> if that waiting fully blocks</div></div>
      <div><div class="delta">${num(r.borrowed_gpu_h)} GPU-h</div><div class="unit">borrowed from people who were away</div></div>
      <div><div class="delta ${overShare > 0.2 ? "badc" : ""}">${pct(overShare, 0)}</div><div class="unit">of borrowed hours overran the window</div></div>
      <div><div class="delta ${r.harm_h > 20 ? "badc" : "okc"}">${r.harm_h} h</div><div class="unit">lenders blocked while borrowed jobs ran</div></div>`;
    $("p-bars").innerHTML = hbars([{ label: "Today", v: base.person_h }, { label: "This pool setting", v: r.person_h },
      { label: "Elastic quota under 70% (reactive)", v: D.tile4.grid.find((g) => g.threshold === 0.7 && !g.idle_kill).person_h, dim: true }], base.person_h);
    $("p-note").innerHTML = gate === "limit"
      ? `<b>Gated on requested limits, the pool never lends.</b> The median requested limit is 24 h against a median runtime of about a minute &mdash;
         a 2,057&times; over-ask &mdash; so almost no job "fits". Only ${num(r.borrowed_gpu_h)} GPU-hours were borrowed.`
      : overShare > 0.2
        ? `A job's runtime is predictable from its owner's history (85% finish within their past p90), so the pool lends &mdash; but
           <b>${pct(overShare, 0)} of borrowed hours ran past the window</b>: rare long jobs carry the hours. Production needs preemption past the window.`
        : `Longer windows lend more and overrun less, while lender harm stays near zero: the lender's own quota is never reduced, so the risk is bounded by design.`;
  };
  $("p-win").addEventListener("input", (e) => { idx = +e.target.value; paint(); });
  $("p-kill").addEventListener("change", (e) => { kill = e.target.checked; paint(); });
  host.querySelectorAll('input[name="p-gate"]').forEach((el) => el.addEventListener("change", (e) => { gate = e.target.value; paint(); }));
  paint();
}

/* =================================================================== TAB 5 == */
function renderTile5() {
  const h = D.hardware, tri = D.triage.summary;
  renderKpis($("t5-kpis"), [
    { value: num(h.point), label: `hardware-caused failures, of ${num(h.failed_jobs_total)}`, sub: `${pct(h.share_of_failed)} — almost everything else is user code` },
    { value: "1 of 113", label: "machine alarms that were really hardware", sub: "86 were people or workload; 26 cannot be determined" },
    { value: "27%", label: "peak PCIe load: data movement is not the bottleneck", sub: "rules::gpu-pcie-saturated is armed and has never fired" },
  ]);
  $("t5-body").innerHTML = `<div class="grid2">
    <div class="panel"><h3>The one machine we would drain</h3>
      <p class="meta"><code>${h.silent_node}</code> ran ${h.silent_window.join(" to ")} and failed 140 of 144 jobs. ${h.note}</p>
      <p class="meta">A second unrelated owner hit the same crash on 2026-03-01; <b>${h.jobs_crashed_after_evidence} more jobs crashed</b> before the
      finding was raised six days later. Draining it then would have cost about <b>${usdFull(h.drain_cost_usd)}</b> of capacity.</p>
      <p class="meta">${h.scheduler_recorded_jobs} jobs had a run killed by a machine death; only ${h.final_nodefail_jobs} still read NODE_FAIL at the end.
      Range ${h.low}&ndash;${h.high}.</p></div>
    <div class="panel"><h3>Why each flagged machine was flagged</h3>
      <p class="meta"><code>rules::node-elevated-failure-rate</code> fired 113 times on 87 machines and gives a symptom with no cause.
      We triaged every one against like-for-like baselines.</p>
      ${table(Object.entries(tri).map(([k, v]) => ({ cause: k.replace(/_/g, " "), n: v })), [{ h: "Cause", k: "cause", l: 1 }, { h: "Findings", k: "n" }])}
      <p class="note"><b>A finding count is not a drain list.</b></p></div></div>
    <div class="panel" style="margin-top:14px"><h3>How to read this</h3>
      <p class="meta">${D.meta.caveat}</p>
      <p class="note">Sources: ${D.meta.sources.map((x) => `<code>${x}</code>`).join(" &middot; ")}. The detection API was
      ${D.meta.api_up ? "live when this page was built" : "unreachable when this page was built"}. Working in
      <code>track-2/ANALYSIS.md</code>, the API review in <code>API_ANALYSIS.md</code>, the numbers in <code>claims.json</code>.
      UI design by Shruti Doshi.</p></div>
    <details style="margin-top:12px"><summary>all 113 verdicts, with the reasoning</summary>
      ${table(D.triage.entries, [{ h: "Machine", k: "node", l: 1, mono: 1 }, { h: "Window", k: "window" },
        { h: "Cause", f: (r) => r.cause.replace(/_/g, " "), l: 1 }, { h: "Action", k: "verdict", l: 1 }, { h: "Reasoning", k: "reasoning", l: 1, wrap: 1 }])}</details>`;
}
