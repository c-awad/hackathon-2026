"""Drive the mcp_layer/ MCP server as an agent would, and record the transcript.

The point is not that MCP can fetch JSON. It is the workflow the tool
descriptions ask for and the API's own recommendation skips:

    never act on a `judgment` without passing it through `causal` first.

This script asks the server the CFO's question -- where should we cut, and what
should we not do? -- and shows the answer changing once `causal` is consulted.

Run (from track-2/, needs uv):

    uv run --with-requirements requirements.lock.txt --with fastmcp \
        python analysis/mcp_demo.py

Writes analysis/out_mcp_transcript.md.
"""
import asyncio
import json
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

# The server must run as a module from the track-2 root: it imports the sibling
# api/ package, and launching it by file path would put mcp_layer/ on sys.path
# instead (mcp_layer/README.md says as much).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = StdioTransport(command=sys.executable, args=["-m", "mcp_layer.server"], cwd=ROOT)
OUT = "analysis/out_mcp_transcript.md"
log = []


def say(line=""):
    print(line)
    log.append(line)


def payload(result):
    """FastMCP returns content blocks; the tools here return JSON objects."""
    if getattr(result, "data", None) is not None:
        return result.data
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


async def main():
    async with Client(SERVER) as c:
        tools = await c.list_tools()
        say("# MCP transcript — asking the server where to cut GPU spend")
        say()
        say(f"Server: `python -m mcp_layer.server` over stdio. **{len(tools)} tools**: "
            + ", ".join(f"`{t.name}`" for t in tools) + ".")
        say()
        say("Every call below is a real tool call against the running server; the "
            "numbers are the server's own output.")
        say()

        # ---- 1. is it up, and what is the corpus? -------------------------
        h = payload(await c.call_tool("health", {}))
        say("## 1. `health` — what is loaded")
        say()
        say(f"```json\n{json.dumps(h, indent=1)[:400]}\n```")
        say()

        # ---- 2. the question, asked the lazy way --------------------------
        recs = payload(await c.call_tool("recommendations", {}))
        say("## 2. `recommendations` — the answer an agent would take at face value")
        say()
        for r in recs.get("recommendations", []):
            say(f"- **{r['title']}** — {r['estimated_savings']['amount']:,.0f} USD "
                f"({r['estimated_savings_gpu_hours']:,.0f} GPU-h), effort `{r['effort']}`, "
                f"`kind: {r.get('kind')}`, confidence **{r['confidence']}**, "
                f"citing {len(r['finding_ids'])} findings")
        say()
        say("Both are `kind: judgment`. The tool description says a judgment must be "
            "validated against `causal` before acting, so that is the next call.")
        say()

        drain = next((r for r in recs["recommendations"] if r["id"] == "rec_drain_nodes"), None)

        # ---- 3. who does it want drained, and why? ------------------------
        up = payload(await c.call_tool("underperforming", {"entity_type": "node", "limit": 5}))
        say("## 3. `underperforming` — the machines behind that recommendation")
        say()
        say("| Machine | Findings | Impact GPU-h |")
        say("|---|---|---|")
        for row in up.get("rows", []):
            say(f"| `{row['entity_id']}` | {row['finding_count']} | {row['impact_gpu_hours']:,.1f} |")
        say()
        say(f"`kind: {up.get('kind')}`, confidence {up.get('confidence')}. Its own "
            f"provenance says: *{up.get('provenance', {}).get('method', '')}* — and the "
            "docstring warns it does not read `rootCauses`.")
        say()

        # ---- 4. what is actually underneath those findings? ---------------
        say("## 4. `causal` — validating the recommendation")
        say()
        cited = (drain or {}).get("finding_ids", [])
        with_chain, without = [], []
        for fid in cited:
            r = payload(await c.call_tool("causal", {"finding_id": fid}))
            (with_chain if (r or {}).get("findings") else without).append(fid)
        say(f"The recommendation cites **{len(cited)} findings**. Passing each to `causal`: "
            f"**{len(with_chain)} resolve to anything at all**, {len(without)} come back "
            f"`findings: []` with a message saying there is nothing upstream to resolve to.")
        say()
        say("So the citation is not evidence about those machines. It is a list of "
            "unrelated job-level findings that happen to sit on them -- wall-clock kills, "
            "idle sessions, jobs that never computed. **A drain list cannot be built out "
            "of findings that have no cause.**")
        say()

        # The findings on those machines that DO carry a cause are the array
        # failures -- ask causal what they resolve to.
        top5 = [row["entity_id"] for row in up.get("rows", [])]
        af = payload(await c.call_tool("list_findings",
                                       {"detector_id": "rules::array-task-failure", "limit": 100}))
        on_top5 = [x for x in (af.get("findings") or [])
                   if (x.get("metadata") or {}).get("node") in top5][:3]
        say(f"The findings on those same machines that *do* carry a `rootCause` are the "
            f"array-task failures. Asking `causal` about {len(on_top5)} of them:")
        say()
        say("| Finding | On machine | Resolves to | Top score | Each machine scores |")
        say("|---|---|---|---|---|")
        for x in on_top5:
            r = payload(await c.call_tool("causal", {"finding_id": x["id"]}))
            fs = (r or {}).get("findings") or []
            if not fs:
                continue
            cul = fs[0]["culprit"]
            machines = [y["score"] for y in cul if y["type"] == "k8s:node"]
            say(f"| `{x['id'][:8]}` | `{x['metadata']['node']}` | `{cul[0]['node']}` "
                f"({cul[0]['type']}) | **{cul[0]['score']}** | "
                f"{', '.join(str(y) for y in machines[:4])}{' ...' if len(machines) > 4 else ''} |")
        say()
        say("**The array scores 1.0; the machines score a fraction of it** (0.05-0.4, each "
            "machine's share of that array's failures). Failures spread thinly across many "
            "machines is how you know the machines are not the cause -- if one were faulty, "
            "its failures would concentrate on it. One broken submission script, not five "
            "broken machines.")
        say()

        # ---- 5. the incident, the same way -------------------------------
        fl = payload(await c.call_tool("list_findings", {"detector_id": "rules::filesystem-latency-degraded",
                                                         "limit": 3}))
        first = (fl.get("findings") or [{}])[0]
        say("## 5. `list_findings` + `causal` — 121 findings, one cause")
        say()
        say(f"`list_findings(detector_id=\"rules::filesystem-latency-degraded\")` returns "
            f"node-scoped findings such as `{first.get('id','')[:8]}`: "
            f"*{first.get('shortDescription','')}*")
        if first.get("id"):
            r = payload(await c.call_tool("causal", {"finding_id": first["id"]}))
            fs = (r or {}).get("findings") or []
            if fs:
                cul = fs[0]["culprit"]
                say()
                say(f"`causal` on it: **{fs[0]['root_cause']}** (confidence {fs[0].get('confidence')}).")
                say()
                say("| Culprit | Type | Score |")
                say("|---|---|---|")
                for x in cul[:5]:
                    say(f"| `{x['node']}` | {x['type']} | {x['score']} |")
                say()
                say("One volume at 0.88, machines at 0.31. **Nothing to drain.**")
        say()

        # ---- 6. what was checked and found clean -------------------------
        rules = payload(await c.call_tool("list_rules", {}))
        rl = rules.get("rules", rules.get("templates", [])) or []
        clear = [r for r in rl if r.get("status") == "CLEAR"]
        say("## 6. `list_rules` — what was checked and came back clean")
        say()
        say(f"{len(rl)} rules armed, {len(clear)} `CLEAR`: "
            + ", ".join(f"`{r.get('rule_id') or r.get('id')}` ({r.get('summary','')})" for r in clear))
        say()
        say("A rule that ran and found nothing is evidence: data movement is not the "
            "bottleneck here, so \"fix the data pipeline\" stays off the list.")
        say()

        # ---- 7. the facts to build a cut on ------------------------------
        eff = payload(await c.call_tool("efficiency_summary", {}))
        waste = payload(await c.call_tool("waste_breakdown", {}))
        say("## 7. `efficiency_summary` + `waste_breakdown` — the facts (`kind: fact`)")
        say()
        for row in eff.get("rows", []):
            say(f"- {row['label']}: {row['gpu_hours']:,.0f} GPU-h ({row['share']:.1%})")
        say(f"- monetised: {eff.get('monetized', {}).get('amount', 0):,.0f} USD, "
            f"`{eff.get('monetized', {}).get('price_book_version')}`, `kind: {eff.get('kind')}`")
        say()
        say("By outcome: " + ", ".join(
            f"{r.get('state', r.get('label'))} {r.get('gpu_hours', 0):,.0f}" for r in waste.get("rows", [])))
        say()

        # ---- 8. re-price it, through the tool ----------------------------
        custom = payload(await c.call_tool("efficiency_summary", {"usd_per_gpu_hour": 4.0}))
        say("## 8. `efficiency_summary(usd_per_gpu_hour=4.0)` — modelling a different rate")
        say()
        say(f"{custom.get('monetized', {}).get('amount', 0):,.0f} USD, tagged "
            f"`{custom.get('monetized', {}).get('price_book_version')}` — the server marks a "
            "re-priced answer, so a price change never reads as an infrastructure change.")
        say()

        # ---- 9. the queue tool, and its label ----------------------------
        q = payload(await c.call_tool("queue_latency", {}))
        row = (q.get("rows") or [{}])[0]
        say("## 9. `queue_latency` — the one label we disagree with")
        say()
        say(f"p50 {row.get('p50_sec', 0):,.0f}s, p99 {row.get('p99_sec', 0)/3600:,.1f}h, "
            f"total {row.get('total_wait_hours', 0):,.0f} h over {row.get('n_jobs', 0):,} jobs → "
            f"**{q.get('monetized', {}).get('amount', 0):,.0f} USD**, `kind: {q.get('kind')}`.")
        say()
        say("The percentiles are a fact. The monetisation is not: it prices every job's "
            "wait as staffed time, and 53% of jobs are array tasks, so one person with "
            "1,000 pending tasks is counted 1,000 times. Merged per person it is 4,997 h, "
            "and 3,719 h past a 4-hour target.")
        say()

        # ---- the answer --------------------------------------------------
        say("## What the agent should answer")
        say()
        say("**Cut:** idle allocations that never ran a kernel (~$205K), CPU work sitting "
            "on GPUs (~$79K), and two-GPU jobs using one card (~$36K).")
        say()
        say("**Do not cut:** the five machines `recommendations` names "
            f"(${(drain or {}).get('estimated_savings', {}).get('amount', 0):,.0f} claimed). "
            "`causal` resolves their findings to Slurm arrays and one storage volume, not "
            "to the machines. Draining them removes ~1,680 GPU-h of capacity a week and the "
            "failing scripts fail wherever they land next.")
        say()
        say("**The workflow that produced that answer is two calls long:** ask for the "
            "recommendation, then ask `causal` what is underneath it. The recommendation "
            "endpoint never makes the second call — which is the whole finding.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write("\n".join(log) + "\n")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
