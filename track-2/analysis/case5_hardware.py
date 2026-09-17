"""Case 5 -- failures genuinely caused by hardware.

Two sources: what the scheduler recorded (NODE_FAIL on any attempt), and a
machine that broke without ever being marked down, found from a pattern of exit
statuses that follow the machine rather than the people.
"""
import json
import pandas as pd

OFFSET = 1750862959
PRICE = 2.50
j = pd.read_parquet("data/prepped/jobs.parquet").set_index("id_job")
g = pd.read_parquet("data/prepped/gpus.parquet")
f = pd.json_normalize(json.load(open("data/synthetic/findings.json")))

j["status"] = (j.exit_code // 256).astype("Int64")
print("exit status sample (FAILED):", j[j.state_name == "FAILED"].status.value_counts().head(8).to_dict())

# ---- 1. What the scheduler recorded ---------------------------------------
hit = j[j.hit_node_failure]
print(f"\nscheduler-recorded: {len(hit)} jobs hit a node failure, {int(hit.nodefail_attempts.sum())} failed attempts,"
      f" final NODE_FAIL {int((hit.state_name == 'NODE_FAIL').sum())}")
print("  final state:", hit.state_name.value_counts().to_dict())
print(f"  located exactly: {int(hit.nodefail_exact.sum())}; lost GPU-h (failed attempts): "
      f"{(hit.nodefail_wall_sec / 3600 * hit.gpu_count).sum():,.0f}")
ex = hit[hit.nodefail_exact]
died = ex.nodefail_nodes.map(lambda v: list(v)[0] if len(v) else None)
print(f"  of exact ones, died on a different machine than the job finished on: "
      f"{(died != ex.primary_node).sum()} / {len(ex)}")
print("  machines that died more than once:", died.value_counts()[lambda s: s > 1].to_dict())

# ---- 2. Find a silent fault: statuses that follow the machine -------------
# Per (node, status): distinct owners who crashed there with that status and
# essentially never produced it anywhere else.
card = g[["id_job", "Node"]].drop_duplicates()
card = card.join(j[["id_user", "state_name", "status", "time_end"]], on="id_job")
fail = card[(card.state_name == "FAILED") & card.status.notna() & (card.status != 0)]

user_status_total = fail.groupby(["id_user", "status"]).id_job.nunique()
here = fail.groupby(["Node", "status", "id_user"]).id_job.nunique().rename("here").reset_index()
here["total"] = here.set_index(["id_user", "status"]).index.map(user_status_total)
here["elsewhere"] = here.total - here.here
jobs_elsewhere = card.groupby("id_user").id_job.nunique()
here["jobs_user"] = here.id_user.map(jobs_elsewhere)
follow = here[(here.here >= 3) & (here.elsewhere == 0)]
sig = follow.groupby(["Node", "status"]).agg(owners=("id_user", "nunique"), crashes=("here", "sum"))
print("\nnode/status pairs where >=2 owners crash (>=3 each) and never elsewhere:")
print(sig[sig.owners >= 2].sort_values("crashes", ascending=False).to_string())
print("with a single owner (user code, not machine):", int((sig.owners == 1).sum()), "pairs")

HW = "r216287-n200569"
hw = f[f.detectorId == "rules::node-hardware-fault"].iloc[0]
lo = pd.Timestamp(hw["metadata.window_start"]).timestamp() - OFFSET
hi = pd.Timestamp(hw["metadata.window_end"]).timestamp() - OFFSET
on = card[(card.Node == HW)].copy()
on["t"] = on.time_end
win = on[(on.t >= lo) & (on.t <= hi)]
print(f"\n{HW}, {hw['metadata.window_start'][:10]} -> {hw['metadata.window_end'][:10]}:"
      f" {win.id_job.nunique()} jobs, {win[win.state_name == 'FAILED'].id_job.nunique()} failed,"
      f" owners failing {win[win.state_name == 'FAILED'].id_user.nunique()}")
print("  failed by status:", win[win.state_name == "FAILED"].groupby("status").id_job.nunique().to_dict())
by_owner = win[win.state_name == "FAILED"].groupby(["id_user", "status"]).id_job.nunique().rename("here").reset_index()
by_owner["owner_fail_rate_elsewhere"] = by_owner.id_user.map(
    card[(card.Node != HW)].groupby("id_user").apply(lambda d: (d.state_name == "FAILED").mean()))
print(by_owner.to_string())

# The machine over time: when did it start and stop failing?
on["day"] = pd.to_datetime(on.t + OFFSET, unit="s").dt.date
daily = on.groupby("day").agg(jobs=("id_job", "nunique"),
                              failed=("state_name", lambda s: (s == "FAILED").sum()),
                              sigbus=("status", lambda s: (s == 135).sum()))
print("\ndaily on", HW, "(days with jobs):")
print(daily[daily.jobs > 0].to_string())

# ---- 3. Why the obvious methods miss it -----------------------------------
nodestats = card.groupby("Node").agg(jobs=("id_job", "nunique"),
                                     failed=("state_name", lambda s: (s == "FAILED").sum()))
nodestats["rate"] = nodestats.failed / nodestats.jobs
print(f"\n{HW} rank by raw failed count: {int(nodestats.failed.rank(ascending=False)[HW])} of {len(nodestats)};"
      f" by failure rate: {int(nodestats.rate.rank(ascending=False)[HW])}")
print(f"  NODE_FAIL ever recorded on it: {int(j.nodefail_nodes.map(lambda v: HW in list(v)).sum())}")
er = f[(f.detectorId == "rules::node-elevated-failure-rate") & (f['metadata.node'] == HW)]
print(f"  node-elevated-failure-rate findings on it: {len(er)}",
      er[["metadata.window_start", "metadata.failed", "metadata.jobs", "metadata.p_value"]].to_dict("records"))
print("  top-5 nodes by raw failures:", nodestats.failed.nlargest(5).to_dict())

# ---- 4. The count ---------------------------------------------------------
sigbus_here = win[(win.state_name == "FAILED") & (win.status == 135)].id_job.nunique()
all_fail_here = win[win.state_name == "FAILED"].id_job.nunique()
lost_hw = j.loc[win[win.state_name == "FAILED"].id_job.unique()].gpu_hours.sum()
print(f"\nsilent machine: SIGBUS failures {sigbus_here}, all failures in window {all_fail_here}, lost GPU-h {lost_hw:,.1f}")
print(f"scheduler-recorded jobs {len(hit)}; of which did not end COMPLETED {int((hit.state_name != 'COMPLETED').sum())}")

# ---- 5. How early could it have been caught, and what would draining cost? --
sb = on[(on.status == 135) & (on.state_name == "FAILED")].sort_values("t")
sb["when"] = pd.to_datetime(sb.t + OFFSET, unit="s")
first_by_owner = sb.groupby("id_user").when.min().sort_values()
print("\nfirst SIGBUS per owner:", first_by_owner.dt.strftime("%m-%d %H:%M").to_dict())
second_owner = first_by_owner.iloc[1]
after = sb[sb.when > second_owner]
print(f"second distinct owner at {second_owner}; SIGBUS crashes after that: {len(after)}"
      f" ({after.id_job.nunique()} jobs); finding detected {hw['detectionTime']}")
bursts = f[(f.detectorId == "rules::node-job-failure-burst") & (f["metadata.node"] == HW)]
print("bursts on this node:", bursts[["metadata.window_start", "metadata.failed", "metadata.jobs",
                                      "metadata.attribution"]].to_dict("records"))
days = (pd.Timestamp(hw["detectionTime"]).tz_localize(None) - second_owner).total_seconds() / 86400
print(f"drain from second owner's crash to detection: {days:.1f} days x 48 GPU-h/day = "
      f"{days*48:,.0f} GPU-h (${days*48*PRICE:,.0f}) of capacity")
