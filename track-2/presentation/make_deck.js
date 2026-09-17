const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";                 // 13.33 x 7.5 in
pres.title = "Team 16 — GPU Spend Review";
const BG = "0E1116", PANEL = "161B22", LINE = "2B3440", INK = "E6EDF3", DIM = "9AA7B4", FAINT = "6E7D8C";
const BLUE = "58A6FF", GREEN = "3FB950", RED = "F85149", AMBER = "D29922", VIOLET = "BC8CFF", CYAN = "39C5CF";
const F = "Calibri";
const T = (s, text, o) => s.addText(text, Object.assign({ fontFace: F, color: INK, margin: 0, isTextBox: true, valign: "top" }, o));
const card = (s, x, y, w, h) => s.addShape(pres.shapes.ROUNDED_RECTANGLE,
  { x, y, w, h, rectRadius: 0.08, fill: { color: PANEL }, line: { color: LINE, width: 0.75 } });
const dot = (s, x, y, color) => s.addShape(pres.shapes.OVAL, { x, y, w: 0.16, h: 0.16, fill: { color }, line: { color, width: 0 } });

/* ------------------------------------------------------------------ slide 1 */
let s = pres.addSlide(); s.background = { color: BG };
T(s, "TEAM 16  ·  TRACK 2  ·  CLUSTER EFFICIENCY", { x: 0.6, y: 0.45, w: 12.1, h: 0.3, fontSize: 12, bold: true, color: BLUE, charSpacing: 2 });
T(s, "Where to cut $1.49M of GPU spend, and what not to touch", { x: 0.6, y: 0.8, w: 12.1, h: 0.75, fontSize: 32, bold: true });

const kpis = [
  ["$359K", GREEN, "recoverable, 24% of spend", "Range $202K to $491K. Clears the 20% target of $297K."],
  ["1", INK, "machine to drain", "Not the 121 the findings suggest, not the 5 the API recommends."],
  ["0.8%", INK, "of failures are hardware", "145 of 18,587. One machine broke silently for a week."],
  ["1,267 h", BLUE, "of waiting removed", "The queue is a quota problem, not a capacity one."],
];
kpis.forEach((k, i) => {
  const x = 0.6 + i * 3.07, w = 2.9;
  card(s, x, 1.8, w, 2.1);
  T(s, k[0], { x: x + 0.22, y: 1.92, w: w - 0.44, h: 0.75, fontSize: 40, bold: true, color: k[1] });
  T(s, k[2], { x: x + 0.22, y: 2.7, w: w - 0.44, h: 0.35, fontSize: 14, bold: true });
  T(s, k[3], { x: x + 0.22, y: 3.08, w: w - 0.44, h: 0.72, fontSize: 12, color: DIM });
});

T(s, "Where the $359K comes from. Every job is counted once.", { x: 0.6, y: 4.2, w: 12.1, h: 0.4, fontSize: 18, bold: true });
const acts = [
  [AMBER, "End idle allocations", "15,070 jobs held GPUs and never ran a kernel.", "−$205K"],
  [VIOLET, "Review barely-used GPUs", "Under 5% busy. We count half: some is real bursty work.", "−$106K"],
  [BLUE, "Move CPU work off GPUs", "Jobs that finished without ever touching their GPU.", "−$31K"],
  [CYAN, "Right-size 2-GPU jobs", "One card worked, one sat idle. Invisible in job tables.", "−$18K"],
];
acts.forEach((a, i) => {
  const x = 0.6 + i * 3.07, w = 2.9;
  card(s, x, 4.7, w, 1.85);
  dot(s, x + 0.22, 4.92, a[0]);
  T(s, a[1], { x: x + 0.46, y: 4.85, w: w - 0.68, h: 0.32, fontSize: 14, bold: true });
  T(s, a[2], { x: x + 0.22, y: 5.25, w: w - 0.44, h: 0.62, fontSize: 12, color: DIM });
  T(s, a[3], { x: x + 0.22, y: 5.95, w: w - 0.44, h: 0.45, fontSize: 22, bold: true, color: GREEN });
});
T(s, "MIT SuperCloud sample: 225 machines, 74,849 jobs, 594,004 GPU-hours, four months, priced at $2.50 per GPU-hour.",
  { x: 0.6, y: 6.85, w: 12.1, h: 0.3, fontSize: 11, color: FAINT });
s.addNotes("Open with the headline: 359 thousand dollars recoverable of 1.49 million, which clears the 20 percent target at the point estimate. Most of the recoverable money is GPUs nobody was using, not machines to switch off and not people to chase. Each job sits in exactly one waste class, so nothing is double counted: summing the detectors' own impact figures would claim 157 percent of the cluster. Cancelled jobs are not counted as waste in themselves, only the idle time before the cancel. Then demo tabs 1 and 2 of the dashboard: the spend wheel, the hatched cut, and clicking a row to drill down to real job ids.");

/* ------------------------------------------------------------------ slide 2 */
s = pres.addSlide(); s.background = { color: BG };
T(s, "What it costs if we are wrong", { x: 0.6, y: 0.5, w: 12.1, h: 0.7, fontSize: 32, bold: true });
T(s, "Four expensive mistakes. Three are suggested by the API itself.", { x: 0.6, y: 1.3, w: 6.9, h: 0.4, fontSize: 16, bold: true });

const cell = (t, o = {}) => ({ text: t, options: Object.assign({ fontFace: F, fontSize: 12, color: INK, valign: "middle", margin: [4, 8, 4, 8] }, o) });
const hdr = (t) => cell(t, { bold: true, color: DIM, fill: { color: PANEL } });
const rows = [
  [hdr("The mistake"), hdr("It claims"), hdr("What it really costs")],
  [cell("Drain the 5 machines with most findings"), cell("$57K saved"), cell("$55K a quarter of capacity, saves nothing", { color: RED })],
  [cell("Drain the 121 storage-incident machines", { fill: { color: PANEL } }), cell("121 problems", { fill: { color: PANEL } }), cell("54% of the cluster offline. It is one volume.", { color: RED, fill: { color: PANEL } })],
  [cell("Count every cancelled job as waste"), cell("$510K waste"), cell("$292K of it was work already computing", { color: RED })],
  [cell("Price queue waiting as salary", { fill: { color: PANEL } }), cell("$9.33M", { fill: { color: PANEL } }), cell("6.3 times the GPU bill. Really 3,719 person-hours.", { color: RED, fill: { color: PANEL } })],
];
s.addTable(rows, { x: 0.6, y: 1.8, w: 6.9, colW: [2.75, 1.4, 2.75], rowH: [0.4, 0.62, 0.62, 0.62, 0.62],
  border: { type: "solid", color: LINE, pt: 0.75 } });
T(s, "The API refutes its own drain advice: POST /v1/causal scores the failing array 1.0 and each machine about 0.14. Our dashboard shows that answer live.",
  { x: 0.6, y: 4.6, w: 6.9, h: 0.8, fontSize: 13, color: DIM });

card(s, 7.9, 1.3, 4.83, 2.55);
dot(s, 8.12, 1.54, BLUE);
T(s, "Researchers wait for quota, not hardware", { x: 8.36, y: 1.46, w: 4.2, h: 0.35, fontSize: 15, bold: true });
T(s, "We replayed all 74,838 jobs. In 90% of long waits the person was at their own cap while 287 of 450 GPUs sat free.",
  { x: 8.12, y: 1.9, w: 4.4, h: 0.8, fontSize: 12, color: DIM });
T(s, [{ text: "Elastic quota plus idle timeout: " }, { text: "−96% waiting", options: { bold: true } },
      { text: ". A safer credits pool: −21%, with 4.3 hours of lender harm in 18 weeks." }],
  { x: 8.12, y: 2.78, w: 4.4, h: 0.9, fontSize: 12 });

card(s, 7.9, 4.05, 4.83, 2.5);
dot(s, 8.12, 4.29, GREEN);
T(s, "Built on the MantisGrid API and MCP", { x: 8.36, y: 4.21, w: 4.2, h: 0.35, fontSize: 15, bold: true });
T(s, "9 of 12 endpoints feed the dashboard. Live causal and price re-pricing on the page. The MCP server driven, with a transcript.",
  { x: 8.12, y: 4.65, w: 4.4, h: 0.8, fontSize: 12, color: DIM });
T(s, [{ text: "3 API bugs found", options: { bold: true } },
      { text: ": neighbor truncates at 500 nodes, queue latency mislabelled as fact, causal quotes inconsistent ratios." }],
  { x: 8.12, y: 5.5, w: 4.4, h: 0.9, fontSize: 12 });

T(s, "Run it: docker compose up, then localhost:3000  ·  Every number reproducible from analysis/  ·  ANALYSIS.md, API_ANALYSIS.md, REPORT.md, claims.json",
  { x: 0.6, y: 6.85, w: 12.1, h: 0.3, fontSize: 11, color: FAINT });
s.addNotes("This is the tile the judges care about most. Walk the table top to bottom. The drain recommendation is the strongest point: the API says drain five machines and save 57 thousand dollars, but it ranks by finding count and never reads root causes; 15 of the 20 findings it cites have no root cause at all, and the API's own causal endpoint says the culprit is a broken array, not the machines. Demo tab 3 and click the first row to show the live causal answer. Then tab 4: move the quota slider, then flip the credits pool between predicted runtime and requested limit to show why requested limits, over-asked about two thousand times, make the pool inert. Close on honesty: hours are reported before dollars, intervals are wide on purpose, and 26 of 113 node alarms are marked cannot determine.");

pres.writeFile({ fileName: "Team16_GPU_Spend_Review.pptx" }).then((f) => console.log("wrote", f));
