"""Bonus for Ritu's headcount question: true workload per team, with the legacy Zoho UTC timestamps fixed.

Usage: python analysis_workload.py   -> evidence/workload_by_team.csv
"""
import pandas as pd

from router.features import RENAMES

t = pd.read_csv("data/train.csv")
r = pd.read_csv("data/resolution_log.csv")
d = t.merge(r, on="request_id")
d["final"] = d.final_team.replace(RENAMES)
d["first"] = d.first_team.replace(RENAMES)
created = pd.to_datetime(d.created_at_ist)
resolved_raw = pd.to_datetime(d.resolved_at)
# Policy §9: resolution events imported from the legacy Zoho log are UTC, never converted. IST = UTC + 5:30.
fix = pd.to_timedelta((d.source == "legacy_zoho").astype(int) * 330, unit="m")
resolved = resolved_raw + fix
d["hours_raw"] = (resolved_raw - created).dt.total_seconds() / 3600
d["hours"] = (resolved - created).dt.total_seconds() / 3600

print("Resolved BEFORE created (raw):", int((d.hours_raw < 0).sum()), "| after UTC fix:", int((d.hours < 0).sum()))
print("Median hours to resolve, Zoho raw vs fixed vs CRM:",
      round(d[d.source == "legacy_zoho"].hours_raw.median(), 1),
      round(d[d.source == "legacy_zoho"].hours.median(), 1),
      round(d[d.source == "crm"].hours.median(), 1))

months = d.created_at_ist.str[:7].nunique()
w = pd.DataFrame({
    "closed_per_month": d.groupby("final").size() / months,
    "bot_sent_per_month": d.groupby("first").size() / months,
    "wrongly_received_per_month": d[d["first"] != d["final"]].groupby("first").size() / months,
    "median_hours_to_resolve": d.groupby("final").hours.median(),
}).round(1).sort_values("closed_per_month", ascending=False)
w.index.name = "team"
w.to_csv("evidence/workload_by_team.csv")
print(w.to_string())
