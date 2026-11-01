"""Train the Kestrel router, back-test it honestly, and write predictions.csv + evidence/.

Usage:
    python train.py            expects the data pack (or a newer CRM export, same columns) in ./data/
    python train.py --force    replace the live model even if the release gate fails

Release gate: a newly trained model replaces models/router.joblib only if its back-test accuracy is no more
than 1 point below the live model's (from models/model_card.json). Otherwise it is saved to models/candidate/.
"""
import json
import os
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import confusion_matrix, f1_score

from router.features import RENAMES, TEAMS, model_input
from router.model import build_pipeline, explain, is_vague

DATA = os.environ.get("KESTREL_DATA", "data")
OUT_EV = "evidence"
COST_TRANSFER, COST_EXTRA_CONTACT, BOT_LICENCE = 305, 260, 320_000
GATE_TOLERANCE = 0.01
os.makedirs(OUT_EV, exist_ok=True)
os.makedirs("models", exist_ok=True)


def load():
    t = pd.read_csv(f"{DATA}/train.csv")
    r = pd.read_csv(f"{DATA}/resolution_log.csv")
    s = pd.read_csv(f"{DATA}/test_unlabelled.csv")
    d = t.merge(r, on="request_id", how="left", validate="1:1")
    assert d.final_team.notna().all()
    # Target = the team that actually CLOSED the request (renames merged), not the bot's first guess.
    d["y"] = d.final_team.replace(RENAMES)
    d["bot"] = d.team_label.replace(RENAMES)
    d["x"] = [model_input(rec) for rec in d.to_dict("records")]
    d["month"] = d.created_at_ist.str[:7]
    d["vague"] = d.request_text.map(is_vague)
    s["x"] = [model_input(rec) for rec in s.to_dict("records")]
    s["vague"] = s.request_text.map(is_vague)
    return d, s


def misroute_cost(d):
    """Average rupee cost of one misrouted request, from the policy's unit costs and actual transfers."""
    mis = d[d.bot != d.y]
    avg_transfers = mis.transfers.mean()
    return avg_transfers * COST_TRANSFER + COST_EXTRA_CONTACT, avg_transfers


def main():
    d, s = load()
    ev = {"n_train": len(d), "n_test": len(s)}

    # ---- 1. Rolling monthly back-test: train on everything before month M, test on M (last 6 months).
    rows = []
    for m in sorted(d.month.unique())[-6:]:
        tr, va = d[d.month < m], d[d.month == m]
        p_final = build_pipeline().fit(tr.x, tr.y).predict(va.x)
        p_bot = build_pipeline().fit(tr.x, tr.bot).predict(va.x)
        rows.append({
            "month": m, "n": len(va),
            "bot_correct": (va.bot == va.y).mean(),
            "model_on_bot_labels__correct": (p_bot == va.y).mean(),
            "model_on_bot_labels__matches_bot": (p_bot == va.bot).mean(),
            "our_model__correct": (p_final == va.y).mean(),
            "our_model__matches_bot": (p_final == va.bot).mean(),
            "our_model_macro_f1": f1_score(va.y, p_final, average="macro"),
            "clear_share": 1 - va.vague.mean(),
            "our_model__correct_clear": (p_final[~va.vague.values] == va.y[~va.vague]).mean(),
            "our_model__correct_vague": (p_final[va.vague.values] == va.y[va.vague]).mean(),
            "bot__correct_clear": (va.bot[~va.vague] == va.y[~va.vague]).mean(),
            "bot__correct_vague": (va.bot[va.vague] == va.y[va.vague]).mean(),
        })
    bt = pd.DataFrame(rows)
    bt.to_csv(f"{OUT_EV}/backtest_by_month.csv", index=False)
    ev["backtest_mean"] = bt.drop(columns=["month", "n"]).mean().round(4).to_dict()
    ev["backtest_min_month_correct"] = round(bt.our_model__correct.min(), 4)
    ev["backtest_max_month_correct"] = round(bt.our_model__correct.max(), 4)

    # ---- 2. One fixed hold-out (Apr-Jun 2026) for per-team and error analysis.
    tr, va = d[d.month < "2026-04"], d[d.month >= "2026-04"].copy()
    pipe = build_pipeline().fit(tr.x, tr.y)
    va["pred"] = pipe.predict(va.x)
    va["conf"] = pipe.predict_proba(va.x).max(axis=1)
    cm = pd.DataFrame(confusion_matrix(va.y, va.pred, labels=TEAMS), index=TEAMS, columns=TEAMS)
    cm.to_csv(f"{OUT_EV}/holdout_confusion_rows_true_cols_pred.csv")
    per_team = []
    for t in TEAMS:
        tp = ((va.pred == t) & (va.y == t)).sum()
        per_team.append({"team": t, "true_n": int((va.y == t).sum()),
                         "precision": round(tp / max((va.pred == t).sum(), 1), 3),
                         "recall": round(tp / max((va.y == t).sum(), 1), 3),
                         "bot_recall": round(((va.bot == t) & (va.y == t)).sum() / max((va.y == t).sum(), 1), 3)})
    pd.DataFrame(per_team).to_csv(f"{OUT_EV}/holdout_per_team.csv", index=False)
    # Policy §3 check: messages that mention paying.
    paid = va.request_text.str.contains(r"\b(?:paid|payment|upi|card)\b", case=False)
    ev["policy3_paid_mentions_holdout"] = {
        "n": int(paid.sum()),
        "bot_sent_to_billing": round((va.bot[paid] == "Billing").mean(), 3),
        "actually_billing": round((va.y[paid] == "Billing").mean(), 3),
        "model_sent_to_billing": round((va.pred[paid] == "Billing").mean(), 3),
        "model_correct": round((va.pred[paid] == va.y[paid]).mean(), 3),
        "bot_correct": round((va.bot[paid] == va.y[paid]).mean(), 3),
    }
    # Confidence buckets: how right is it when it says it is sure?
    va["bucket"] = pd.cut(va.conf, [0, 0.45, 0.7, 0.9, 1.0])
    ev["holdout_accuracy_by_confidence"] = {
        str(k): {"share": round(len(g) / len(va), 3), "correct": round((g.pred == g.y).mean(), 3)}
        for k, g in va.groupby("bucket", observed=True)
    }
    auto = (~va.vague) & (va.conf >= 0.45)
    ev["holdout_auto_route"] = {"share": round(auto.mean(), 3), "correct": round((va.pred[auto] == va.y[auto]).mean(), 3)}
    errs = va[va.pred != va.y][["request_id", "channel", "product_family", "warranty_status", "request_text",
                                "bot", "pred", "y", "conf", "vague", "transfers"]]
    errs = errs.rename(columns={"y": "final_team"})
    # Customer text stays out of the public repo (ops policy §10): full version is git-ignored.
    os.makedirs(f"{OUT_EV}/private", exist_ok=True)
    errs.to_csv(f"{OUT_EV}/private/holdout_errors_with_text.csv", index=False)
    errs.drop(columns=["request_text"]).to_csv(f"{OUT_EV}/holdout_errors.csv", index=False)
    ev["holdout_errors"] = {"n": len(errs), "share_vague": round(errs.vague.mean(), 3)}

    # ---- 3. Rupees.
    cost_per_mis, avg_tr = misroute_cost(d)
    monthly_volume = len(s) / 3  # test covers Jul-Sep 2026
    yearly = monthly_volume * 12
    bot_err = 1 - bt.bot_correct.mean()
    model_err = 1 - bt.our_model__correct.mean()
    clear_share = 1 - s.vague.mean()
    ev["money"] = {
        "avg_transfers_per_misroute": round(avg_tr, 2),
        "cost_per_misroute_rs": round(cost_per_mis),
        "requests_per_year_est": round(yearly),
        "bot_misroute_rate": round(bot_err, 4),
        "model_misroute_rate": round(model_err, 4),
        "bot_misroute_cost_per_year_rs": round(yearly * bot_err * cost_per_mis),
        "model_misroute_cost_per_year_rs": round(yearly * model_err * cost_per_mis),
        "saving_misroutes_per_year_rs": round(yearly * (bot_err - model_err) * cost_per_mis),
        "saving_licence_per_year_rs": BOT_LICENCE,
        "run_cost_per_month_rs": 0,
        "test_clear_share": round(clear_share, 3),
    }
    ev["money"]["total_saving_per_year_rs"] = (ev["money"]["saving_misroutes_per_year_rs"] + BOT_LICENCE)

    # ---- 4. Final model on ALL labelled data. Release gate: never replace a better live model.
    new_acc = float(bt.our_model__correct.mean())
    card_path = "models/model_card.json"
    if os.path.exists(card_path) and os.path.exists("models/router.joblib") and "--force" not in sys.argv:
        with open(card_path) as f:
            old = json.load(f)
        old_acc = old.get("backtest_accuracy", 0)
        if new_acc < old_acc - GATE_TOLERANCE:
            final = build_pipeline().fit(d.x, d.y)
            os.makedirs("models/candidate", exist_ok=True)
            joblib.dump(final, "models/candidate/router.joblib")
            print(f"RELEASE GATE FAILED: new back-test accuracy {new_acc:.4f} is worse than live model "
                  f"{old_acc:.4f} (tolerance {GATE_TOLERANCE}). Live model untouched; candidate saved to "
                  f"models/candidate/. Use --force to override after review.")
            return 2
    final = build_pipeline().fit(d.x, d.y)
    joblib.dump(final, "models/router.joblib")
    card = {
        "model_version": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "trained_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "target": "final_team (team that resolved the request), renamed teams merged",
        "training_rows": int(len(d)),
        "training_period": [d.created_at_ist.min()[:10], d.created_at_ist.max()[:10]],
        "backtest_accuracy": round(new_acc, 4),
        "backtest_accuracy_clear": round(float(bt.our_model__correct_clear.mean()), 4),
        "backtest_accuracy_vague": round(float(bt.our_model__correct_vague.mean()), 4),
        "bot_accuracy_same_period": round(float(bt.bot_correct.mean()), 4),
        "confidence_floor": 0.45,
        "teams": TEAMS,
    }
    with open(card_path, "w") as f:
        json.dump(card, f, indent=2)
    ev["model_card"] = card
    s["team"] = final.predict(s.x)
    sub = pd.read_csv(f"{DATA}/sample_submission.csv")[["request_id"]].merge(s[["request_id", "team"]], how="left")
    assert sub.team.notna().all() and set(sub.team) <= set(TEAMS) and len(sub) == len(s)
    sub.to_csv("predictions.csv", index=False)
    s["conf"] = final.predict_proba(s.x).max(axis=1)
    s["action"] = np.where(s.vague, "clarify_first", np.where(s.conf < 0.45, "check", "auto_route"))
    ev["test_predicted_volume_by_team"] = s.team.value_counts().to_dict()
    ev["test_actions"] = s.action.value_counts(normalize=True).round(3).to_dict()
    ev["history_volume_by_final_team_per_month"] = (d.groupby("y").size() / d.month.nunique()).round(0).to_dict()

    # ---- 5. Expected score on hidden outcomes.
    # Back-test accuracy split into clear vs vague, re-weighted to the test set's clear/vague mix.
    bm = ev["backtest_mean"]
    exp = clear_share * bm["our_model__correct_clear"] + (1 - clear_share) * bm["our_model__correct_vague"]
    ev["expected_test_accuracy"] = round(exp, 4)
    ev["expected_test_accuracy_range"] = [ev["backtest_min_month_correct"], ev["backtest_max_month_correct"]]

    # Sample explanations for the README / evidence
    ev["sample_explanations"] = [
        {"request_id": rec["request_id"], **explain(final, rec)}
        for rec in s.sample(4, random_state=7).to_dict("records")
    ]
    with open(f"{OUT_EV}/metrics.json", "w") as f:
        json.dump(ev, f, indent=2, default=str)
    print(json.dumps({k: ev[k] for k in ["backtest_mean", "money", "expected_test_accuracy",
                                          "expected_test_accuracy_range", "holdout_auto_route",
                                          "policy3_paid_mentions_holdout", "test_actions",
                                          "holdout_accuracy_by_confidence"]}, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
