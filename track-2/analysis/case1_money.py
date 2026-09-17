"""Case 1 -- where the money goes. GPU-hour weighted, priced at the 2026-Q3 book."""
import pandas as pd

PRICE = 2.50
j = pd.read_parquet("data/prepped/jobs.parquet")
total = j.gpu_hours.sum()

def usd(h): return f"${h * PRICE:>12,.0f}"

print(f"allocated {total:,.0f} GPU-h  {usd(total)}")

# how much of the held time the GPU was actually busy (SM util is 0-100)
computed = (j.gpu_hours * j.sm_util_avg / 100).sum()
print(f"computed  {computed:,.0f} GPU-h  ({computed/total:.1%})")

print("\nby outcome")
by = j.groupby("state_name").agg(jobs=("id_job", "size"), gpu_h=("gpu_hours", "sum"))
by["busy_h"] = j.assign(b=j.gpu_hours * j.sm_util_avg / 100).groupby("state_name").b.sum()
by["share"] = by.gpu_h / total
by["usd"] = by.gpu_h * PRICE
print(by.sort_values("gpu_h", ascending=False).to_string(float_format=lambda x: f"{x:,.2f}"))

print("\nby job type")
jt = j.groupby("job_type").agg(jobs=("id_job", "size"), gpu_h=("gpu_hours", "sum"))
jt["util_w"] = j.assign(b=j.gpu_hours * j.sm_util_avg).groupby("job_type").b.sum() / jt.gpu_h
jt["share"] = jt.gpu_h / total
print(jt.sort_values("gpu_h", ascending=False).to_string(float_format=lambda x: f"{x:,.2f}"))

print("\nby utilization band (hour-weighted)")
bands = pd.cut(j.sm_util_avg, [-0.01, 0, 5, 20, 50, 80, 100],
               labels=["0% (never ran)", "0-5%", "5-20%", "20-50%", "50-80%", "80-100%"])
ub = j.groupby(bands, observed=True).agg(jobs=("id_job", "size"), gpu_h=("gpu_hours", "sum"))
ub["share"] = ub.gpu_h / total
print(ub.to_string(float_format=lambda x: f"{x:,.3f}"))

print("\noutcome x band, GPU-h")
print(pd.crosstab(bands, j.state_name, values=j.gpu_hours, aggfunc="sum").round(0).fillna(0).to_string())

print("\nby width")
w = pd.cut(j.gpu_count, [0, 1, 2, 8, 64], labels=["1", "2", "3-8", "9+"])
wb = j.groupby(w, observed=True).agg(jobs=("id_job", "size"), gpu_h=("gpu_hours", "sum"))
wb["share"] = wb.gpu_h / total
wb["util_w"] = j.assign(b=j.gpu_hours * j.sm_util_avg).groupby(w, observed=True).b.sum() / wb.gpu_h
print(wb.to_string(float_format=lambda x: f"{x:,.2f}"))

print("\nconcentration: users", )
u = j.groupby("id_user").gpu_hours.sum().sort_values(ascending=False)
for k in (5, 10, 20):
    print(f"  top {k} users: {u.head(k).sum()/total:.1%} of GPU-h")
