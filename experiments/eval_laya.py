"""Experiment: can Laya (github.com/NandhaKishorM/laya, Apache-2.0) route Kestrel requests zero-shot?

Compares Laya against our committed model on the same hold-out requests (Apr-Jun 2026), scored
against the team that actually resolved each request. Not part of the service; optional.

Setup (needs internet; first run downloads a ~1 GB checkpoint):
    pip install laya pandas scikit-learn==1.9.1
    python experiments/eval_laya.py            # default 400 requests
    python experiments/eval_laya.py --n 2135   # whole hold-out (slow on CPU)

Run it on your own machine: the data pack is customer data (ops policy §10).
"""
import argparse
import os
import sys
import time

import joblib
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from router.features import RENAMES, model_input  # noqa: E402
from router.model import is_vague  # noqa: E402

# Team descriptions from teams.csv, plus the Billing rule from ops policy §3.
CRITERIA = {
    "Repairs": "Product faults, breakdowns, error codes, noise, leaks, not turning on - anything that needs a technician to fix.",
    "Installs & Demo": "New-product installation, demo and wall-mounting visits; installer not coming; installation slot or reschedule.",
    "Filters & Consumables": "Buying or fitting filters, candles, membranes, jars, brushes, blades, AMC kits and spares. Not faults.",
    "Billing": "Only when the problem IS the payment: invoice, GST, double charge, refund of a payment, EMI conversion, coupon. "
               "A customer saying they have paid does not make it billing.",
    "Returns & Replacement": "Damaged, wrong, used or incomplete deliveries; returns, pickups and exchanges within the return window.",
    "Warranty Claims": "Warranty and Kestrel Shield registration, coverage questions, warranty certificate, claim status.",
    "Product Advice": "Pre- and post-purchase usage questions: which model to buy, how to use or clean it. No fault reported.",
}
QUESTIONS = {
    "team": {
        "type": "choice",
        "instructions": "Which Kestrel Home service team should handle this customer request?",
        "criteria": CRITERIA,
    }
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    args = ap.parse_args()

    from laya import Router  # imported here so a missing install gives a clear message below

    t = pd.read_csv(f"{args.data}/train.csv")
    r = pd.read_csv(f"{args.data}/resolution_log.csv")
    d = t.merge(r, on="request_id")
    d = d[d.created_at_ist >= "2026-04"].copy()
    d["y"] = d.final_team.replace(RENAMES)
    d["bot"] = d.team_label.replace(RENAMES)
    d = d.sample(min(args.n, len(d)), random_state=0)
    d["vague"] = d.request_text.map(is_vague)

    # Our model, retrained WITHOUT the hold-out months so the comparison is fair.
    from router.model import build_pipeline
    full = t.merge(r, on="request_id")
    tr = full[full.created_at_ist < "2026-04"]
    ours = build_pipeline().fit([model_input(x) for x in tr.to_dict("records")], tr.final_team.replace(RENAMES))
    d["ours"] = ours.predict([model_input(x) for x in d.to_dict("records")])

    router = Router()
    preds, t0 = [], time.time()
    for i, rec in enumerate(d.to_dict("records")):
        state = (f"Channel: {rec['channel']}. Product: {rec['product_family']}. "
                 f"Warranty: {rec['warranty_status']}. Customer message: {rec['request_text']}")
        try:
            preds.append(router.predict(state, QUESTIONS)["answers"]["team"]["choice"])
        except Exception as exc:  # keep going; count it as wrong
            preds.append(f"ERROR: {exc.__class__.__name__}")
        if (i + 1) % 50 == 0:
            print(f"{i + 1}/{len(d)}  {(time.time() - t0) / (i + 1):.2f}s per request")
    d["laya"] = preds
    secs = (time.time() - t0) / len(d)

    rows = []
    for name in ["bot", "ours", "laya"]:
        rows.append({
            "router": name,
            "correct_all": (d[name] == d.y).mean(),
            "correct_clear": (d[name][~d.vague] == d.y[~d.vague]).mean(),
            "correct_vague": (d[name][d.vague] == d.y[d.vague]).mean(),
        })
    out = pd.DataFrame(rows).round(3)
    print(f"\n{len(d)} hold-out requests, Laya {secs:.2f}s per request on this machine\n")
    print(out.to_string(index=False))
    os.makedirs(os.path.join(ROOT, "evidence"), exist_ok=True)
    out.to_csv(os.path.join(ROOT, "evidence", "laya_comparison.csv"), index=False)
    d[["request_id", "y", "bot", "ours", "laya", "vague"]].to_csv(
        os.path.join(ROOT, "evidence", "laya_predictions_holdout.csv"), index=False)


if __name__ == "__main__":
    try:
        main()
    except ImportError as exc:
        sys.exit(f"Laya is not installed ({exc}). Run: pip install laya")
