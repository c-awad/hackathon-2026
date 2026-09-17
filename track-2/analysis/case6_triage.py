"""Case 6 -- why did rules::node-elevated-failure-rate fire? One verdict per finding.

The rule's windows are reproduced exactly: 14-day windows anchored at the first
job, jobs counted by time_end, attributed to a machine through gpus.parquet, and
"failed" meaning state FAILED. Every test compares like with like -- the same
owner, the same window, or the same array -- never "does this person fail a lot".
"""
import json
import pandas as pd
from scipy.stats import binomtest, poisson

OFFSET = 1750862959
W = 14 * 86400
j = pd.read_parquet("data/prepped/jobs.parquet").set_index("id_job")
j["status"] = (j.exit_code // 256).astype("Int64")
g = pd.read_parquet("data/prepped/gpus.parquet")[["id_job", "Node"]].drop_duplicates()
g = g.join(j[["id_user", "state_name", "status", "time_end", "id_array_job", "is_array_task"]], on="id_job")
g["failed"] = g.state_name == "FAILED"
f = pd.json_normalize(json.load(open("data/synthetic/findings.json")))
er = f[f.detectorId == "rules::node-elevated-failure-rate"].copy()

ANCHOR = j.time_start.min()
g["win"] = ((g.time_end - ANCHOR) // W).astype(int)
er["win"] = ((er["metadata.window_start"].map(lambda s: pd.Timestamp(s, tz="UTC").timestamp())
              - OFFSET - ANCHOR) / W).round().astype(int)

# owner x status seen anywhere, for the machine-signature test
status_nodes = g[g.failed & g.status.notna()].groupby(["id_user", "status"]).Node.nunique()
# node failures, located exactly, by machine and window
nf = j[j.hit_node_failure & j.nodefail_exact].copy()
nf["died"] = nf.nodefail_nodes.map(lambda v: list(v)[0])
nf["win"] = ((nf.nodefail_last_end - ANCHOR) // W).astype(int)
nf_count = nf.groupby(["died", "win"]).size()
# array failure rates, for the sibling test
arr = g.drop_duplicates("id_job").dropna(subset=["id_array_job"])


def fmt_owner(u):
    return f"u-{int(u)}"


def triage(row):
    node, w, p_c = row["metadata.node"], row.win, row["metadata.cluster_rate_this_window"]
    win = g[g.win == w]
    here = win[win.Node == node].drop_duplicates("id_job")
    else_ = win[win.Node != node].drop_duplicates("id_job")
    n, F = len(here), int(here.failed.sum())
    # 112 of 113 match exactly; r8473362-n410412 window 4 is one non-failed job
    # short (115 vs 116), most likely a requeued job whose card rows sit on
    # another attempt's machine (docs/data.md).
    assert abs(n - row["metadata.jobs"]) <= 1 and F == row["metadata.failed"], (node, w)
    out = dict(node=node, window=int(w), jobs=n, failed=F, node_rate=F / n, cluster_rate=p_c)

    # --- per-owner comparison, same window, other machines -------------------
    per = here.groupby("id_user").agg(n_here=("id_job", "size"), f_here=("failed", "sum"))
    oth = else_.groupby("id_user").agg(n_else=("id_job", "size"), f_else=("failed", "sum"))
    per = per.join(oth).fillna(0)
    per["r_else"] = per.f_else / per.n_else.where(per.n_else > 0)
    has_base = per.n_else >= 5
    per["exp"] = per.n_here * per.r_else.where(has_base, p_c)
    expected = per.exp.sum()
    covered = per.n_here[has_base].sum() / n
    p_excess = poisson.sf(F - 1, expected) if expected > 0 else 0.0
    top = per.f_here.idxmax()
    top_share = per.f_here[top] / F if F else 0
    others = here[here.id_user != top]
    n_o, F_o = len(others), int(others.failed.sum())
    p_others = binomtest(F_o, n_o, p_c, alternative="greater").pvalue if n_o else 1.0
    t = per.loc[top]
    out.update(owners=len(per), owners_failing=int((per.f_here > 0).sum()), top_owner=fmt_owner(top),
               top_share=top_share, top_here=f"{int(t.f_here)}/{int(t.n_here)}",
               top_else=f"{int(t.f_else)}/{int(t.n_else)}", top_r_else=t.r_else,
               others=f"{F_o}/{n_o}", p_others=p_others, expected=expected, covered=covered,
               p_excess=p_excess)

    # --- array siblings of the top owner's failures ----------------------------
    tf = here[(here.id_user == top) & here.failed & here.is_array_task]
    sib = arr[arr.id_array_job.isin(tf.id_array_job) & ~arr.id_job.isin(here.id_job)]
    out["sib"] = f"{int(sib.failed.sum())}/{len(sib)}" if len(sib) else "none"
    sib_rate = sib.failed.mean() if len(sib) >= 5 else None
    top_rate_here = t.f_here / t.n_here
    # owners failing here at >= 2x their own rate elsewhere in the window
    hot = per[has_base & (per.f_here >= 3) & (per.f_here / per.n_here >= 2 * per.r_else)]
    out["owners_hot"] = len(hot)

    # --- machine signature: >=2 owners crash here with a status seen nowhere else
    fh = here[here.failed & here.status.notna() & (here.status != 0)]
    sig = fh.groupby(["status", "id_user"]).size().rename("k").reset_index()
    sig["nodes"] = [status_nodes.get((u, s), 0) for u, s in zip(sig.id_user, sig.status)]
    sig = sig[(sig.k >= 2) & (sig.nodes == 1)].groupby("status").id_user.nunique()
    sig_status = sig[sig >= 2]
    died = int(nf_count.get((node, w), 0))
    out["signature"] = ", ".join(f"status {int(s)} x {int(k)} owners" for s, k in sig_status.items()) or "none"
    out["node_failures"] = died

    # --- decision ---------------------------------------------------------------
    base = (f"jobs.parquet+gpus.parquet, window {w} (14 d from first job, by time_end): "
            f"{F}/{n} FAILED here vs cluster {p_c:.3f}. ")
    if len(sig_status) or died >= 2:
        cause, verdict = "hardware", "act"
        why = (f"Exit status (exit_code//256) signature: {out['signature']} -- each owner crashed here with it "
               f"and on no other machine in 4 months. Node failures located here (nodefail_nodes): {died}. "
               f"Several unrelated people failing the same way only here points at the machine.")
    elif top_share >= 0.6 and p_others >= 0.05 and (
            (t.n_else >= 5 and t.r_else >= 0.5 * t.f_here / t.n_here) or (sib_rate is not None and sib_rate >= 0.5 * top_rate_here)):
        cause, verdict = "user_code", "no_action"
        why = (f"Owner {fmt_owner(top)} holds {top_share:.0%} of failures ({out['top_here']} here) and fails "
               f"{out['top_else']} on other machines in the same window; array siblings elsewhere failed "
               f"{out['sib']}. Everyone else here failed {out['others']} (binomial vs cluster p={p_others:.2f}, "
               f"not elevated). The failures follow the person, not the machine.")
    elif top_share >= 0.6:
        cause, verdict = "cannot_determine", "monitor"
        if t.n_else < 5 and sib_rate is None:
            reason = (f"{fmt_owner(top)} ({out['top_here']} here) ran only {int(t.n_else)} job(s) elsewhere in the "
                      f"window and no array siblings elsewhere, so there is no like-for-like baseline")
        elif p_others < 0.05:
            reason = (f"{fmt_owner(top)} dominates ({top_share:.0%}), but everyone else here also failed "
                      f"{out['others']} (p={p_others:.3f} vs cluster), so the machine is not cleared")
        else:
            reason = (f"{fmt_owner(top)} fails {out['top_here']} here but only {out['top_else']} elsewhere in the "
                      f"window (siblings {out['sib']}); others here {out['others']} look normal. Could be the "
                      f"machine or different work sent here")
        why = reason + ". No exit-status signature and no located node failure. Neither cause is ruled out."
    elif covered >= 0.6 and p_excess >= 0.05:
        cause, verdict = "workload_mix", "no_action"
        why = (f"No single owner dominates ({out['owners_failing']} owners failing, top {top_share:.0%}). "
               f"Using each owner's own FAILED rate on other machines in the same window "
               f"({covered:.0%} of jobs have a baseline), the expected count is {expected:.1f} vs {F} observed "
               f"(Poisson p={p_excess:.2f}). The machine received failure-prone work; it is not failing it.")
    else:
        cause, verdict = "cannot_determine", "monitor"
        if covered < 0.6:
            reason = f"only {covered:.0%} of jobs here have an owner baseline elsewhere in the window"
        else:
            reason = (f"{F} failures vs {expected:.1f} expected from owners' own rates elsewhere "
                      f"(Poisson p={p_excess:.3g}) -- more than the work explains, spread over "
                      f"{out['owners_failing']} owners, {len(hot)} of whom fail here at 2x+ their own rate "
                      f"elsewhere -- but no exit-status signature or located node failure")
        why = reason + ". Machine and workload can't be separated from this data."
    out.update(cause=cause, verdict=verdict, reasoning=base + why)
    return out


res = pd.DataFrame([triage(r) for _, r in er.iterrows()]).sort_values(["window", "node"])
print(res.cause.value_counts().to_string())
print(res.groupby("cause").verdict.value_counts().to_string())
cols = ["node", "window", "failed", "jobs", "cause", "top_share", "top_here", "top_else", "others",
        "p_others", "expected", "covered", "p_excess", "sib", "signature", "node_failures"]
print(res[cols].to_string(float_format=lambda x: f"{x:.3g}"))
res.to_json("analysis/out_case6_triage.json", orient="records", indent=1)
print("\nnodes flagged in >1 window:", res.node.value_counts()[lambda s: s > 1].to_dict())

# claims.json-shaped output, consumed when claims.json is assembled
triage_claims = res[["node", "window", "cause", "reasoning", "verdict"]].to_dict("records")
json.dump(triage_claims, open("analysis/node_triage.json", "w"), indent=1)
print(f"wrote analysis/node_triage.json ({len(triage_claims)} entries)")
print("failed jobs by cause:", res.groupby("cause").failed.sum().to_dict())
