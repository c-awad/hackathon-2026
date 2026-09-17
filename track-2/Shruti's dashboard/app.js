/* Three tabs, each a few plain numbers and one picture. Everything else is in the
   report, which is built only when someone asks for it. data.json comes from build.py. */

const $ = (id) => document.getElementById(id);

const usd = (n) => {
  if (n === null || n === undefined) return "--";
  const a = Math.abs(n);
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${Math.round(n / 1e3).toLocaleString()}K`;
  return `$${Math.round(n).toLocaleString()}`;
};
const num = (n) => (n === null || n === undefined ? "--" : Math.round(n).toLocaleString());
const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`;
const hours = (n) => `${num(n)} GPU-h`;
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
};

/* One colour per bucket, so the eye can follow a bucket across all three tabs. */
const HUE = {
  never_used: "#d29922",
  barely_used: "#bc8cff",
  cpu_work: "#58a6ff",
  idle_card: "#39c5cf",
  killed_by_clock: "#f85149",
  productive: "#3fb950",
};

let D = null;

fetch("data.json")
  .then((r) => r.json())
  .then((d) => {
    D = d;
    renderHeader();
    renderTile1();
    renderTile2();
    renderTile3();
    wireTabs();
    wireReport();
  })
  .catch((e) => {
    document.querySelector("main").prepend(
      el("div", "callout warnbox",
        `<strong>No data.json.</strong> Run <code>python "Shruti's dashboard/build.py"</code> from
         <code>track-2/</code> first — it needs <code>data/prepped/</code>. (${e})`)
    );
  });

/* ----------------------------------------------------------------------- tabs */
const TILES = ["tile1", "tile2", "tile3"];
let activeTile = "tile1";

/* `main` is the scroll container, not the window, so reset both. */
function toTop() {
  const m = document.querySelector("main");
  if (m) m.scrollTop = 0;
  window.scrollTo({ top: 0 });
}

function showTile(id) {
  document.querySelectorAll(".donut-wrap").forEach((w) => w._hideWheelGuide?.());
  activeTile = id;
  [...$("tabs").children].forEach((t) => {
    const on = t.dataset.tile === id;
    t.setAttribute("aria-selected", on ? "true" : "false");
    const panel = $(t.dataset.tile);
    if (on) panel.removeAttribute("hidden");
    else panel.setAttribute("hidden", "");
  });
  if (location.hash !== `#${id}`) history.replaceState(null, "", `#${id}`);
  toTop();
}

function wireTabs() {
  [...$("tabs").children].forEach((t) =>
    t.addEventListener("click", () => { closeReport(); showTile(t.dataset.tile); }));
  const initial = location.hash.replace("#", "");
  showTile(TILES.includes(initial) ? initial : "tile1");
}

/* --------------------------------------------------------------------- header */
function renderHeader() {
  const m = D.meta;
  $("title").textContent = m.title;
  $("subtitle").textContent = m.subtitle;
  const c = m.cluster;
  $("footer").innerHTML =
    `${c.nodes} machines, ${c.gpus_per_node} GPUs each &middot; ${num(c.jobs)} jobs from ` +
    `${c.users} researchers &middot; ${num(c.gpu_hours)} GPU-hours at ` +
    `$${m.price_book.usd_per_gpu_hour.toFixed(2)}/hour (price book ${m.price_book.version}).` +
    `<br>${m.caveat} Full workings, sources and caveats are in the report.`;
}

/* Three big numbers, no jargon, at the top of every tab. */
function renderKpis(box, kpis) {
  box.innerHTML = "";
  kpis.forEach((k) => {
    box.append(el("div", "kpi",
      `<strong>${k.value}</strong><span class="kpi-label">${k.label}</span>
       <span class="kpi-sub">${k.sub}</span>`));
  });
}

/* ================================================================== TAB 1 == */
/* The tab bar already names the tab, so the tiles carry no heading of their own. */
function renderTile1() {
  const t = D.tile1;
  renderKpis($("t1-kpis"), t.kpis);
  drawDonut($("c-donut"), t.headline);
  bucketRows($("t1-buckets"), (b) => ({
    sub: `${num(b.now.jobs)} jobs &middot; the card was computing ${b.now.busy_pct}% of the time`,
    figs: `<strong>${usd(b.now.usd)}</strong>
           <span class="row-note">${pct(b.now.share_of_bill, 0)} of the bill</span>`,
  }));
}

/* The spend wheel. Both wheels draw the same geometry: one arc per bucket, sized by
   its share of the whole bill. On tab 2 the cut part of each arc is greyed and
   hatched, so it is visibly the same wheel with bites taken out of it.
   Hover is a transparent sector on top of each slice — the painted arcs stay
   stroke-dasharray so the two tabs still match to the pixel. */
let wheelCount = 0;
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

function drawDonut(svg, headline) {
  drawWheel(svg, D.spine.map((b) => ({
    key: b.key,
    kept: b.now.share_of_bill,
    tip: {
      name: b.name,
      plain: b.plain,
      figs: `${usd(b.now.usd)} · ${pct(b.now.share_of_bill, 0)} of the bill`,
      sub: `${num(b.now.jobs)} jobs · the card was computing ${b.now.busy_pct}% of the time`,
    },
  })), [
    { text: usd(headline.usd), size: 30, colour: "#e6edf3", weight: 600 },
    { text: "total GPU bill", size: 11.5, colour: "#6e7d8c", gap: 4 },
  ]);
}

/* Tab 2: same wheel, reduced bill in the middle, cut portions hatched out. */
function drawCutWheel(svg, w) {
  const byKey = Object.fromEntries(D.spine.map((b) => [b.key, b]));
  drawWheel(svg, w.segments.map((s) => {
    const b = byKey[s.key];
    const cut = s.cut_share_of_bill;
    return {
      key: s.key,
      kept: s.kept_share_of_bill,
      cut,
      tip: {
        name: b.name,
        plain: b.plain,
        figs: cut > 0
          ? `&minus;${usd(s.cut_usd)} hatched cut · ${usd(s.kept_usd)} stays`
          : `${usd(s.kept_usd)} stays · nothing hatched`,
        sub: b.cut.action,
      },
    };
  }), [
    { text: `was ${usd(w.before_usd)}`, size: 12, colour: "#6e7d8c", strike: true },
    { text: usd(w.after_usd), size: 30, colour: "#3fb950", weight: 600, gap: 4 },
    { text: `&minus;${usd(w.cut_usd)} (${pct(w.cut_share, 0)})`, size: 12.5, colour: "#e6edf3", gap: 2 },
  ]);
}

/* One row per bucket, in spine order on both tabs, coloured to match its slice.
   Row n on tab 1 and row n on tab 2 are always the same bucket. */
function bucketRows(box, figures) {
  box.innerHTML = "";
  const wrap = box.closest(".two-col")?.querySelector(".donut-wrap");
  D.spine.forEach((b) => {
    const row = el("div", "row");
    row.dataset.key = b.key;
    row.style.borderLeftColor = HUE[b.key];
    const f = figures(b);
    row.innerHTML =
      `<div class="row-main">
         <span class="row-title">${b.name}</span>
         <span class="row-sub">${f.sub}</span>
       </div>
       <div class="row-figs">${f.figs}</div>`;
    if (wrap) {
      row.addEventListener("pointerenter", () => wrap._showWheelGuide?.(b.key));
      row.addEventListener("pointerleave", () => wrap._hideWheelGuide?.());
    }
    box.append(row);
  });
}

/* ================================================================== TAB 2 == */
function renderTile2() {
  const t = D.tile2;
  renderKpis($("t2-kpis"), t.kpis);
  drawCutWheel($("t2-wheel"), t.wheel);
  bucketRows($("t2-actions"), (b) => ({
    sub: `${b.cut.action} <i>${b.cut.owner === "--" ? "" : b.cut.owner}</i>`,
    figs: b.cut.gpu_hours > 0
      ? `<strong class="cut-val">&minus;${usd(b.cut.usd)}</strong>
         <span class="row-note ${b.cut.confidence}">${b.cut.confidence} confidence</span>`
      : `<strong class="none-val">no cut</strong>
         <span class="row-note">${usd(b.now.usd)} stays</span>`,
  }));
}

/* ================================================================== TAB 3 == */
function renderTile3() {
  const t = D.tile3;
  renderKpis($("t3-kpis"), t.kpis);

  const box = $("t3-risks");
  box.innerHTML = "";
  t.risks.forEach((r) => {
    const row = el("div", `row level-${r.level.replace(/ /g, "-")}`);
    row.innerHTML =
      `<div class="row-main">
         <span class="row-title">${r.claim}</span>
         <span class="row-sub">${r.what_if_wrong}</span>
       </div>
       <div class="row-figs">
         <strong>${r.amount}</strong>
         <span class="level">${r.level}</span>
       </div>`;
    box.append(row);
  });
}

/* ================================================================= REPORT == */
let reportBuilt = false;

function wireReport() {
  $("report-btn").addEventListener("click", openReport);
  $("report-close").addEventListener("click", () => { closeReport(); showTile(activeTile); });
  $("report-print").addEventListener("click", () => window.print());
  $("report-md").addEventListener("click", downloadMarkdown);
}

function openReport() {
  if (!reportBuilt) {
    $("report-btn").textContent = "Building report\u2026";
    buildReport();
    reportBuilt = true;
    $("report-btn").textContent = "Full report";
  }
  TILES.forEach((id) => $(id).setAttribute("hidden", ""));
  $("tabs").setAttribute("hidden", "");
  $("report").removeAttribute("hidden");
  toTop();
}

function closeReport() {
  $("report").setAttribute("hidden", "");
  $("tabs").removeAttribute("hidden");
}

/* Everything the tabs deliberately leave out, assembled in one pass. */
function buildReport() {
  const body = $("report-body");
  const m = D.meta, t1 = D.tile1, t2 = D.tile2, t3 = D.tile3;

  body.innerHTML = `
    <h2 class="r-h1">${m.title}</h2>
    <p class="report-meta">Generated ${new Date().toLocaleString()} from
      ${m.sources.map((s) => `<code>${s}</code>`).join(" and ")}, priced at
      $${m.price_book.usd_per_gpu_hour.toFixed(2)} per GPU-hour (price book ${m.price_book.version}).</p>

    <h3 class="r-h2">1. ${t1.title}</h3>
    <p class="r-p">${t1.question} ${t1.reading}</p>
    <div class="r-charts">
      <figure class="fig">
        <figcaption><b>What happened to each dollar</b> — paid for, computing, then finished work.</figcaption>
        <svg id="r-funnel" viewBox="0 0 440 260" role="img"></svg>
      </figure>
      <figure class="fig">
        <figcaption><b>How busy the card was in each bucket</b> — the share of held time it spent
          calculating.</figcaption>
        <svg id="r-busy" viewBox="0 0 440 260" role="img"></svg>
      </figure>
      <figure class="fig">
        <figcaption><b>How the jobs ended</b> — the solid part of each bar was computing, the faded
          part was not.</figcaption>
        <svg id="r-outcome" viewBox="0 0 440 260" role="img"></svg>
      </figure>
      <figure class="fig">
        <figcaption><b>Who holds the capacity</b> — researchers ordered biggest first, against their
          running share of the bill.</figcaption>
        <svg id="r-conc" viewBox="0 0 440 260" role="img"></svg>
      </figure>
    </div>
    <h4 class="r-h3">The six buckets in full</h4>
    <div class="spine" id="r-spine-now"></div>

    <h3 class="r-h2">2. ${t2.title}</h3>
    <p class="r-p">${t2.reading}</p>
    <h4 class="r-h3">How sure we are of the total</h4>
    <div class="bars" id="r-bars"></div>
    <div class="callout" id="r-verdict"></div>
    <h4 class="r-h3">What each bucket gives back</h4>
    <div class="spine" id="r-spine-cut"></div>
    <h4 class="r-h3">Ranked by what it returns</h4>
    <div id="r-ranked"></div>
    <h4 class="r-h3">How long we let an unused GPU sit before ending the job</h4>
    <figure class="fig">
      <svg id="r-grace" viewBox="0 0 520 190" role="img"></svg>
      <figcaption id="r-grace-note"></figcaption>
    </figure>

    <h3 class="r-h2">3. ${t3.title}</h3>
    <p class="r-p">${t3.reading}</p>
    <div class="spine" id="r-spine-tradeoff"></div>
    <h4 class="r-h3">Trade-off 1 — every idle-kill rule, priced</h4>
    <p class="r-p">Each row is a rule somebody could ship, at a
      ${graceLabel(t3.simulator.graces[t3.simulator.default.g])} grace period. Savings are what it
      frees; the last three columns are what it was wrong about.</p>
    <div id="r-policy"></div>
    <p class="r-p dim">${t3.simulator.note}</p>
    <h4 class="r-h3">Trade-off 2 — the same question, answered two ways</h4>
    <div id="r-defs" class="cards"></div>
    <h4 class="r-h3">Trade-off 3 — before we drain a machine</h4>
    <p class="r-p" id="r-nodes-why"></p>
    <div class="callout warnbox" id="r-drain"></div>
    <div class="split">
      <div><h5 class="r-h4">Ranked by number of failures</h5><div id="r-nodes-count"></div></div>
      <div><h5 class="r-h4">Ranked by failure rate</h5><div id="r-nodes-rate"></div></div>
    </div>
    <p class="r-p dim" id="r-nodes-overlap"></p>

    <h3 class="r-h2">4. What this data cannot tell us</h3>
    <div id="r-limits" class="limits"></div>
    <p class="r-p dim">${m.caveat} <code>rules::gpu-imbalance</code> is recomputed here rather than
      read from the findings, reproducing it exactly:
      ${m.rules_recomputed["gpu-imbalance"].jobs} jobs,
      ${num(m.rules_recomputed["gpu-imbalance"].idle_gpu_hours)} idle card GPU-hours.</p>`;

  drawFunnel($("r-funnel"), t1.funnel);
  drawBusyBars($("r-busy"));
  drawOutcomeBars($("r-outcome"), t1.by_outcome);
  drawConcentration($("r-conc"), t1.concentration);

  renderSpine($("r-spine-now"), "now");
  renderSpine($("r-spine-cut"), "cut");
  renderSpine($("r-spine-tradeoff"), "tradeoff");
  renderEstimateBars($("r-bars"), $("r-verdict"));
  $("r-ranked").append(rankedTable());
  $("r-grace-note").textContent = t2.grace_sweep.note;
  drawSimpleBars($("r-grace"), t2.grace_sweep.hours.map(graceLabel),
    t2.grace_sweep.hours.map((h) => t2.grace_sweep.gpu_hours[String(h)]), HUE.never_used);

  $("r-policy").append(policyTable());
  renderDefinitions($("r-defs"));
  renderNodes();
  const lim = $("r-limits");
  t3.limits.forEach((l) => lim.append(el("div", "limit", `<b>${l.limit}</b><p>${l.consequence}</p>`)));
}

/* The spine: the same six rows three times, one column swapped out. */
function renderSpine(box, mode) {
  box.innerHTML = "";
  const max = Math.max(...D.spine.map((b) => b.now.gpu_hours));

  D.spine.forEach((b) => {
    const row = el("div", "spine-row");
    row.style.borderLeftColor = HUE[b.key];

    const head = el("div", "spine-head");
    head.append(el("span", "spine-name", b.full_name || b.name));
    head.append(el("span", "spine-plain", b.plain));
    row.append(head);

    const mid = el("div", "spine-mid");
    if (mode === "now") {
      const track = el("div", "spine-track");
      const fill = el("div", "spine-fill");
      fill.style.width = `${(b.now.gpu_hours / max) * 100}%`;
      fill.style.background = HUE[b.key];
      track.append(fill);
      mid.append(track);
      mid.append(el("div", "spine-note",
        `${num(b.now.jobs)} jobs &middot; the card was computing ${b.now.busy_pct}% of the time it was
         held. ${b.now.note}`));
      row.append(mid);
      row.append(el("div", "spine-figs",
        `<strong>${usd(b.now.usd)}</strong>
         <span>${num(b.now.gpu_hours)} GPU-h &middot; ${pct(b.now.share_of_bill)} of the bill</span>`));
    } else if (mode === "cut") {
      const track = el("div", "spine-track");
      const whole = el("div", "spine-fill ghost");
      whole.style.width = `${(b.now.gpu_hours / max) * 100}%`;
      const cutBar = el("div", "spine-fill cut");
      cutBar.style.width = `${(b.cut.gpu_hours / max) * 100}%`;
      cutBar.style.background = HUE[b.key];
      track.append(whole, cutBar);
      mid.append(track);
      mid.append(el("div", "spine-note",
        b.cut.gpu_hours > 0
          ? `<b>${b.cut.action}</b> ${b.cut.basis} Owner: ${b.cut.owner}.`
          : `<b>${b.cut.action}</b> ${b.cut.basis}`));
      row.append(mid);
      row.append(el("div", "spine-figs",
        b.cut.gpu_hours > 0
          ? `<strong class="cut-val">${usd(b.cut.usd)}</strong>
             <span>${pct(b.cut.share_of_bucket, 0)} of this bucket
             &middot; <span class="conf conf-${b.cut.confidence}">${b.cut.confidence} confidence</span></span>`
          : `<strong class="none-val">no cut</strong><span>of ${usd(b.now.usd)} in this bucket</span>`));
    } else {
      mid.append(el("div", "spine-note", `<b>If we are wrong:</b> ${b.tradeoff.what_breaks}`));
      mid.append(el("div", "spine-note dim", `<b>Defence:</b> ${b.tradeoff.defence}`));
      row.append(mid);
      row.append(el("div", "spine-figs",
        `<span class="risk risk-${b.tradeoff.risk.replace(/ /g, "-")}">${
          b.tradeoff.risk === "not a cut" ? "not a cut" : `${b.tradeoff.risk} risk`}</span>
         <strong class="cost-val">${b.tradeoff.cost_usd ? usd(b.tradeoff.cost_usd) : "--"}</strong>
         <span>${b.tradeoff.cost_gpu_hours ? `${num(b.tradeoff.cost_gpu_hours)} GPU-h at stake` : "nothing at stake"}</span>`));
    }
    box.append(row);
  });
}

/* Cautious, best guess and optimistic, against the 20% target line. */
function renderEstimateBars(box, verdictBox) {
  const t = D.tile2;
  const scale = Math.max(t.total.high.gpu_hours, t.target.gpu_hours) * 1.06;
  box.innerHTML = "";
  ["low", "point", "high"].forEach((k) => {
    const e = t.total[k];
    const row = el("div", "bar-row");
    row.append(el("div", "bar-name",
      k === "point" ? "best guess" : k === "low" ? "cautious" : "optimistic"));
    const track = el("div", "bar-track");
    const fill = el("div", `bar-fill ${k}`);
    fill.style.width = `${(e.gpu_hours / scale) * 100}%`;
    track.append(fill);
    const tgt = el("div", "bar-target");
    tgt.style.left = `${(t.target.gpu_hours / scale) * 100}%`;
    track.append(tgt);
    row.append(track);
    row.append(el("div", "bar-value",
      `<strong>${usd(e.usd)}</strong><span>${hours(e.gpu_hours)} &middot; ${pct(e.share)} of the bill</span>`));
    row.append(el("div", "bar-basis", e.basis));
    box.append(row);
  });

  const short = t.target.gpu_hours - t.total.low.gpu_hours;
  verdictBox.innerHTML =
    `The CFO was told to cut <strong>20%</strong>, which is <strong>${usd(t.target.usd)}</strong>
     (${hours(t.target.gpu_hours)}). ${t.verdict} If the cautious reading is the right one, the target
     is missed by <strong>${usd(short * D.meta.price_book.usd_per_gpu_hour)}</strong> and the rest has
     to come from somewhere else.`;
}

function rankedTable() {
  const table = el("table");
  table.innerHTML =
    `<thead><tr><th>#</th><th>Action</th><th>Returns</th><th>Who has to act</th>
     <th>Confidence</th><th>Risk</th></tr></thead>`;
  const body = el("tbody");
  D.tile2.ranked.forEach((r) => {
    body.append(el("tr", null,
      `<td>${r.rank}</td>
       <td><span class="dot" style="background:${HUE[r.key]}"></span>${r.action}</td>
       <td><b>${usd(r.usd)}</b></td><td class="wrap">${r.owner}</td>
       <td><span class="conf conf-${r.confidence}">${r.confidence}</span></td>
       <td><span class="risk risk-${r.risk.replace(/ /g, "-")}">${r.risk}</span></td>`));
  });
  table.append(body);
  return table;
}

/* Every policy at the default grace, so the reader can see savings bought with damage. */
function policyTable() {
  const s = D.tile3.simulator;
  const g = s.default.g;
  const table = el("table");
  table.innerHTML =
    `<thead><tr><th>Safety guard</th><th>Counts as unused below</th><th>Frees</th>
     <th>Destroys work</th><th>Jobs ended</th><th>&hellip;that finished</th>
     <th>Bursty jobs caught</th></tr></thead>`;
  const body = el("tbody");
  s.guards.forEach((gd) => {
    s.thresholds.forEach((thr, ti) => {
      const c = s.grid.find((x) => x.g === g && x.t === ti && x.guard === gd.key);
      const safe = c.busy_destroyed_gpu_hours === 0 && c.bursty_jobs_hit === 0;
      body.append(el("tr", safe ? "safe-row" : null,
        `<td class="wrap">${ti === 0 ? gd.label : ""}</td>
         <td>${thr === 0 ? "never used at all" : `${thr}% average`}</td>
         <td><b>${usd(c.returns_usd)}</b></td>
         <td class="${c.busy_destroyed_usd > 0 ? "bad-cell" : ""}">${usd(c.busy_destroyed_usd)}</td>
         <td>${num(c.jobs)}</td><td>${num(c.completed_jobs_hit)}</td>
         <td class="${c.bursty_jobs_hit > 0 ? "bad-cell" : ""}">${num(c.bursty_jobs_hit)}${
          c.bursty_jobs_hit > 0 ? ` <i>(${hours(c.bursty_gpu_hours_hit)})</i>` : ""}</td>`));
    });
  });
  table.append(body);
  return table;
}

function renderDefinitions(box) {
  box.innerHTML = "";
  D.tile3.definitions.forEach((d) => {
    const card = el("div", "card risk-medium");
    card.append(el("h4", null, d.question));
    d.options.forEach((o) => {
      const val = o.gpu_hours !== undefined
        ? `${usd(o.usd)} <span class="dimval">/ ${num(o.gpu_hours)} h</span>`
        : `${o.pct}%`;
      const badge = o.verdict === "defensible" ? "defensible"
        : o.verdict === "overstates" ? "overstates" : "true";
      card.append(el("div", "opt-row",
        `<span>${o.label}<span class="badge ${badge}">${o.verdict}</span></span>
         <span class="opt-val">${val}</span>`));
    });
    if (d.cost_usd) {
      card.append(el("p", "costline",
        `Picking the first one promises <b>${usd(d.cost_usd)}</b> we cannot hand back
         (${num(d.cost_gpu_hours)} GPU-h).`));
    }
    card.append(el("p", "defence", d.why));
    box.append(card);
  });
}

function renderNodes() {
  const n = D.tile3.nodes;
  $("r-nodes-why").textContent = n.why;
  $("r-drain").innerHTML =
    `Draining the five worst-looking machines for a quarter removes
     <strong>${hours(n.drain_cost.gpu_hours)}</strong> of capacity, worth
     <strong>${usd(n.drain_cost.usd)}</strong> — and if the failures belong to a script rather than the
     machine, that script fails on whatever machine it lands on next and the capacity is gone for nothing.`;
  $("r-nodes-count").append(nodeTable(n.by_count));
  $("r-nodes-rate").append(nodeTable(n.by_rate));
  $("r-nodes-overlap").textContent =
    `The two rankings share ${n.ranking_overlap} of 10 machines. Rows tinted amber are machines where a ` +
    `single researcher owns half or more of the failures, so the machine is probably not at fault — the ` +
    `cluster's overall failure rate is ${pct(n.cluster_failure_rate)}. Rate ranking only considers ` +
    `machines with at least ${n.exposure.exposure_floor} jobs, because exposure runs from ` +
    `${n.exposure.min_jobs} to ${num(n.exposure.max_jobs)} jobs per machine.`;
}

function nodeTable(rows) {
  const t = el("table");
  t.innerHTML =
    `<thead><tr><th>Machine</th><th>Jobs</th><th>Failed</th><th>Rate</th>
     <th>GPU-h served</th><th>Biggest owner</th></tr></thead>`;
  const body = el("tbody");
  rows.forEach((r) => {
    const tr = el("tr", r.one_owner_dominates ? "owned" : null);
    const owner = r.top_owner_share_of_failures === null ? "--"
      : `${pct(r.top_owner_share_of_failures, 0)}${
        r.one_owner_dominates ? ' <span class="flag">one owner</span>' : ""}`;
    tr.innerHTML =
      `<td class="node">${r.node}</td><td>${num(r.jobs)}</td><td>${num(r.failures)}</td>
       <td>${pct(r.failure_rate, 0)}</td><td>${num(r.gpu_hours_served)}</td><td>${owner}</td>`;
    body.append(tr);
  });
  t.append(body);
  return t;
}

/* --------------------------------------------------------- markdown download */
function downloadMarkdown() {
  const blob = new Blob([reportMarkdown()], { type: "text/markdown" });
  const a = el("a");
  a.href = URL.createObjectURL(blob);
  a.download = "gpu-spend-report.md";
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

function reportMarkdown() {
  const m = D.meta, t1 = D.tile1, t2 = D.tile2, t3 = D.tile3;
  const L = [];
  const table = (head, rows) => {
    L.push(`| ${head.join(" | ")} |`, `|${head.map(() => "---").join("|")}|`);
    rows.forEach((r) => L.push(`| ${r.join(" | ")} |`));
    L.push("");
  };

  L.push(`# ${m.title}`, "", m.subtitle, "",
    `Generated ${new Date().toISOString().slice(0, 16).replace("T", " ")} from ` +
    `${m.sources.join(" and ")}, priced at $${m.price_book.usd_per_gpu_hour.toFixed(2)} per ` +
    `GPU-hour (price book ${m.price_book.version}).`, "",
    `Cluster: ${m.cluster.nodes} machines, ${m.cluster.gpus_per_node} GPUs each, ` +
    `${num(m.cluster.jobs)} jobs from ${m.cluster.users} researchers, ` +
    `${num(m.cluster.gpu_hours)} GPU-hours.`, "");

  L.push("## Headline", "");
  [t1, t2, t3].forEach((t) => t.kpis.forEach((k) => L.push(`- **${k.value}** ${k.label} — ${k.sub}`)));
  L.push("");

  L.push(`## 1. ${t1.title}`, "", t1.question, "", t1.reading, "");
  table(["Stage", "GPU-hours", "Cost", "Cents per dollar"],
    t1.funnel.map((s) => [s.label, num(s.gpu_hours), usd(s.usd), `${s.cents}c`]));
  table(["Bucket", "Jobs", "GPU-hours", "Cost", "Share of bill", "Card busy"],
    D.spine.map((b) => [b.full_name || b.name, num(b.now.jobs), num(b.now.gpu_hours),
      usd(b.now.usd), pct(b.now.share_of_bill), `${b.now.busy_pct}%`]));
  table(["Outcome", "GPU-hours", "Cost", "Card busy"],
    t1.by_outcome.map((r) => [r.outcome, num(r.gpu_hours), usd(r.usd), `${r.busy_pct}%`]));
  L.push(`Concentration: ` + t1.concentration.markers
    .map((k) => `the top ${k.users} researchers hold ${pct(k.share, 0)} of the bill`).join("; ") +
    `, out of ${t1.concentration.users_total}.`, "");

  L.push(`## 2. ${t2.title}`, "", t2.question, "", t2.reading, "");
  table(["Reading", "GPU-hours", "Cost", "Share of bill", "Basis"],
    ["low", "point", "high"].map((k) => {
      const e = t2.total[k];
      return [k === "point" ? "best guess" : k === "low" ? "cautious" : "optimistic",
        num(e.gpu_hours), usd(e.usd), pct(e.share), e.basis];
    }));
  L.push(`Target is a 20% cut: ${usd(t2.target.usd)} (${hours(t2.target.gpu_hours)}). ${t2.verdict}`, "");
  table(["#", "Action", "Returns", "Who has to act", "Confidence", "Risk"],
    t2.ranked.map((r) => [r.rank, r.action, usd(r.usd), r.owner, r.confidence, r.risk]));
  table(["Bucket", "Cut", "Share of bucket", "Basis", "Confidence"],
    D.spine.map((b) => [b.full_name || b.name, usd(b.cut.usd),
      pct(b.cut.share_of_bucket), b.cut.basis, b.cut.confidence]));
  table(["Grace period", "GPU-hours returned"],
    t2.grace_sweep.hours.map((h) => [graceLabel(h), num(t2.grace_sweep.gpu_hours[String(h)])]));
  L.push(t2.grace_sweep.note, "");

  L.push(`## 3. ${t3.title}`, "", t3.question, "");
  table(["Call", "Verdict", "Amount", "What happens if we are wrong"],
    t3.risks.map((r) => [r.claim, r.level, r.amount, r.what_if_wrong]));
  table(["Bucket", "Risk", "What breaks", "At stake", "Defence"],
    D.spine.map((b) => [b.full_name || b.name, b.tradeoff.risk, b.tradeoff.what_breaks,
      b.tradeoff.cost_usd ? usd(b.tradeoff.cost_usd) : "--", b.tradeoff.defence]));

  const s = t3.simulator;
  L.push(`### Every idle-kill rule at a ${graceLabel(s.graces[s.default.g])} grace period`, "");
  table(["Guard", "Unused below", "Frees", "Destroys work", "Jobs ended", "...that finished", "Bursty caught"],
    s.guards.flatMap((gd) => s.thresholds.map((thr, ti) => {
      const c = s.grid.find((x) => x.g === s.default.g && x.t === ti && x.guard === gd.key);
      return [gd.label, thr === 0 ? "never used at all" : `${thr}% average`, usd(c.returns_usd),
        usd(c.busy_destroyed_usd), num(c.jobs), num(c.completed_jobs_hit),
        `${num(c.bursty_jobs_hit)} (${hours(c.bursty_gpu_hours_hit)})`];
    })));
  L.push(s.note, "");

  L.push("### Definitions that swing the headline", "");
  t3.definitions.forEach((d) => {
    L.push(`**${d.question}**`, "");
    d.options.forEach((o) => L.push(`- ${o.label}: ` +
      (o.gpu_hours !== undefined ? `${usd(o.usd)} (${num(o.gpu_hours)} GPU-h)` : `${o.pct}%`) +
      ` — *${o.verdict}*`));
    if (d.cost_usd) L.push("", `Cost of the wrong choice: ${usd(d.cost_usd)}.`);
    L.push("", d.why, "");
  });

  const n = t3.nodes;
  L.push("### Before draining a machine", "", n.why, "",
    `Draining five machines for a quarter costs ${hours(n.drain_cost.gpu_hours)} of capacity, ` +
    `worth ${usd(n.drain_cost.usd)}. The two rankings below share ${n.ranking_overlap} of 10 machines; ` +
    `the cluster failure rate is ${pct(n.cluster_failure_rate)}.`, "");
  table(["Ranking", "Machine", "Jobs", "Failed", "Rate", "GPU-h served", "Biggest owner's share"],
    [...n.by_count.map((r) => ["by count", r.node, num(r.jobs), num(r.failures),
      pct(r.failure_rate, 0), num(r.gpu_hours_served),
      r.top_owner_share_of_failures === null ? "--" : pct(r.top_owner_share_of_failures, 0)]),
    ...n.by_rate.map((r) => ["by rate", r.node, num(r.jobs), num(r.failures),
      pct(r.failure_rate, 0), num(r.gpu_hours_served),
      r.top_owner_share_of_failures === null ? "--" : pct(r.top_owner_share_of_failures, 0)])]);

  L.push("## 4. What this data cannot tell us", "");
  t3.limits.forEach((l) => L.push(`- **${l.limit}** — ${l.consequence}`));
  L.push("", m.caveat, "",
    `\`rules::gpu-imbalance\` is recomputed here rather than read from the findings, reproducing it ` +
    `exactly: ${m.rules_recomputed["gpu-imbalance"].jobs} jobs, ` +
    `${num(m.rules_recomputed["gpu-imbalance"].idle_gpu_hours)} idle card GPU-hours.`, "");
  return L.join("\n");
}

/* ---------------------------------------------------------------- svg charts */
const graceLabel = (g) => (g === 0 ? "none" : g < 1 ? `${g * 60} min` : `${g} hour${g === 1 ? "" : "s"}`);

/* Three stages of the same dollar. */
function drawFunnel(svg, stages) {
  const W = 440, padL = 12, padR = 12, top = 22, rowH = 72;
  const max = stages[0].gpu_hours;
  let out = "";
  stages.forEach((s, i) => {
    const y = top + i * rowH;
    const w = (s.gpu_hours / max) * (W - padL - padR);
    const shade = ["#1f6f2c", "#2f7d8a", "#7d5d1f"][i];
    out += `<rect x="${padL}" y="${y}" width="${w.toFixed(1)}" height="40" rx="4" fill="${shade}"/>`;
    out += `<text x="${padL + 10}" y="${y + 18}" fill="#e6edf3" font-size="13"
      font-weight="600">${s.label}</text>`;
    out += `<text x="${padL + 10}" y="${y + 33}" fill="#c9d4df" font-size="11.5">${
      usd(s.usd)} &#183; ${num(s.gpu_hours)} GPU-h</text>`;
    out += `<text x="${W - padR}" y="${y + 26}" fill="#e6edf3" font-size="21" font-weight="600"
      text-anchor="end">${s.cents}&#162;</text>`;
    if (i > 0) {
      const lost = stages[i - 1].gpu_hours - s.gpu_hours;
      out += `<text x="${padL + 2}" y="${y - 6}" fill="#f85149" font-size="10.5">&#8595; ${
        usd(lost * D.meta.price_book.usd_per_gpu_hour)} lost here</text>`;
    }
  });
  out += `<text x="${padL}" y="${top + 3 * rowH + 8}" fill="#6e7d8c" font-size="11">${
    stages[2].note}</text>`;
  svg.innerHTML = out;
}

/* How much of each bucket's held time was actually computing. */
function drawBusyBars(svg) {
  const rows = [...D.spine].sort((a, b) => b.now.busy_pct - a.now.busy_pct);
  // the row pitch comes from the viewBox, so more buckets cannot push the note out of it
  const W = 440, Hh = 260, padL = 12, padR = 44, top = 12, noteH = 16;
  const rowH = (Hh - top - noteH) / rows.length;
  let out = "";
  rows.forEach((b, i) => {
    const y = top + i * rowH;
    const full = W - padL - padR;
    out += `<text x="${padL}" y="${y + 11}" fill="#c9d4df" font-size="11.5">${b.name}</text>`;
    out += `<rect x="${padL}" y="${y + 16}" width="${full}" height="10" rx="3" fill="#131a21"/>`;
    out += `<rect x="${padL}" y="${y + 16}" width="${(full * b.now.busy_pct / 100).toFixed(1)}"
      height="10" rx="3" fill="${HUE[b.key]}"/>`;
    out += `<text x="${W - padR + 8}" y="${y + 25}" fill="#e6edf3" font-size="12"
      font-variant-numeric="tabular-nums">${b.now.busy_pct}%</text>`;
  });
  out += `<text x="${padL}" y="${Hh - 4}" fill="#6e7d8c" font-size="11">` +
    `Cluster-wide, hour-weighted: ${D.tile1.funnel[1].cents}% of held time.</text>`;
  svg.innerHTML = out;
}

/* Hours per outcome, split into the part that was computing and the part that was not. */
function drawOutcomeBars(svg, rows) {
  const W = 440, Hh = 260, padL = 12, padR = 12, top = 12;
  const rowH = (Hh - top - 6) / rows.length;
  const max = Math.max(...rows.map((r) => r.gpu_hours));
  const full = W - padL - padR;
  let out = "";
  rows.forEach((r, i) => {
    const y = top + i * rowH;
    const w = (r.gpu_hours / max) * full;
    const busyW = w * (r.busy_pct / 100);
    out += `<text x="${padL}" y="${y + 11}" fill="#c9d4df" font-size="11.5">${r.outcome}</text>`;
    out += `<text x="${W - padR}" y="${y + 11}" fill="#6e7d8c" font-size="11"
      text-anchor="end">${usd(r.usd)} &#183; ${r.busy_pct}% busy</text>`;
    out += `<rect x="${padL}" y="${y + 16}" width="${w.toFixed(1)}" height="14" rx="3"
      fill="#58a6ff" opacity="0.22"/>`;
    out += `<rect x="${padL}" y="${y + 16}" width="${busyW.toFixed(1)}" height="14" rx="3"
      fill="#58a6ff"/>`;
  });
  svg.innerHTML = out;
}

/* Cumulative share of the bill as researchers are added, biggest first. */
function drawConcentration(svg, c) {
  // padB leaves two baselines: the axis ends, then the dashed-line key below them
  const W = 440, Hh = 260, padL = 40, padR = 14, padT = 14, padB = 44;
  const plotW = W - padL - padR, plotH = Hh - padT - padB;
  const n = c.users_total;
  const x = (u) => padL + (u / n) * plotW;
  const y = (s) => padT + plotH - s * plotH;
  let out = "";
  for (let i = 0; i <= 4; i++) {
    const gy = padT + plotH - (plotH * i) / 4;
    out += `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="#2b3440"/>`;
    out += `<text x="${padL - 7}" y="${gy + 4}" fill="#6e7d8c" font-size="10"
      text-anchor="end">${i * 25}%</text>`;
  }
  const pts = c.curve.map((p) => `${x(p.users).toFixed(1)},${y(p.share).toFixed(1)}`).join(" ");
  out += `<polygon points="${padL},${y(0)} ${pts} ${x(n)},${y(0)}" fill="#58a6ff" opacity="0.13"/>`;
  out += `<polyline points="${pts}" fill="none" stroke="#58a6ff" stroke-width="2"/>`;
  // a straight line would mean everybody spends the same
  out += `<line x1="${padL}" y1="${y(0)}" x2="${x(n)}" y2="${y(1)}" stroke="#6e7d8c"
    stroke-width="1" stroke-dasharray="3 3"/>`;
  c.markers.forEach((mk) => {
    out += `<circle cx="${x(mk.users)}" cy="${y(mk.share)}" r="3.5" fill="#d29922"/>`;
    out += `<text x="${x(mk.users) + 7}" y="${y(mk.share) - 5}" fill="#d29922" font-size="10.5">top ${
      mk.users}: ${pct(mk.share, 0)}</text>`;
  });
  out += `<text x="${padL}" y="${Hh - 27}" fill="#6e7d8c" font-size="10.5">1 researcher</text>`;
  out += `<text x="${W - padR}" y="${Hh - 27}" fill="#6e7d8c" font-size="10.5"
    text-anchor="end">all ${n}</text>`;
  out += `<text x="${W / 2}" y="${Hh - 8}" fill="#6e7d8c" font-size="10"
    text-anchor="middle">&#8212; dashed: everyone spending equally</text>`;
  svg.innerHTML = out;
}

function drawSimpleBars(svg, labels, values, colour) {
  const max = Math.max(...values, 1);
  paint(svg, labels, values.map((v) => [[v, colour]]), max, -1);
}

function paint(svg, labels, groups, max, highlight) {
  const W = 520, Hh = 190, padL = 52, padB = 26, padT = 12;
  const plotH = Hh - padB - padT;
  const slot = (W - padL - 10) / groups.length;
  const bars = groups[0].length;
  const bw = Math.min(18, (slot - 8) / bars);
  let out = "";
  for (let i = 0; i <= 2; i++) {
    const y = padT + plotH - (plotH * i) / 2;
    out += `<line x1="${padL}" y1="${y}" x2="${W - 6}" y2="${y}" stroke="#2b3440" stroke-width="1"/>`;
    out += `<text x="${padL - 8}" y="${y + 4}" fill="#6e7d8c" font-size="10" text-anchor="end">${
      Math.round((max * i) / 2 / 1000)}k</text>`;
  }
  groups.forEach((grp, i) => {
    const x0 = padL + i * slot + (slot - bw * bars) / 2;
    if (i === highlight) {
      out += `<rect x="${padL + i * slot + 1}" y="${padT}" width="${slot - 2}" height="${plotH}"
        fill="#58a6ff" opacity="0.10" rx="3"/>`;
    }
    grp.forEach(([val, colour], si) => {
      const h = val > 0 ? Math.max((val / max) * plotH, 1.5) : 0;
      out += `<rect x="${x0 + si * bw}" y="${padT + plotH - h}" width="${bw - 2}" height="${h}"
        fill="${colour}" rx="1.5"/>`;
    });
    out += `<text x="${padL + i * slot + slot / 2}" y="${Hh - 8}" fill="${
      i === highlight ? "#58a6ff" : "#6e7d8c"}" font-size="10" text-anchor="middle">${labels[i]}</text>`;
  });
  svg.innerHTML = out;
}
