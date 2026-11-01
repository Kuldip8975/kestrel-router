"""Kestrel service-request router: model building, prediction and human-readable reasons."""
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline, make_union

from .features import TEAMS, clean_text, model_input

# Requests that name no concrete problem. Nobody - the old bot, an agent, or this model - can route
# these from the text; history shows their final team is close to random (see evidence/).
VAGUE = re.compile(
    r"\b(query|call back|call me|contact me|issue with|complaint about|help with|need help|"
    r"not happy|problem|service request|help \w+)\b"
)
SPECIFIC = re.compile(
    r"(not turning on|not working|error|noise|leak|tripping|burnt|stopped|blank|install|demo|filter|"
    r"candle|membrane|jar|brush|blade|amc|spare|invoice|gst|double|charged|refund|emi|coupon|damaged|"
    r"wrong|missing|return|exchange|replace|used|warranty|shield|claim|regist|how to|clean|recipe|usage|"
    r"smell|heating|spinning|reschedul|slot|installer|pickup|cancel|price|reminder)"
)
PAID = re.compile(r"\b(paid|payment|upi|card|already paid|paid extra)\b")
BILLING_PROBLEM = re.compile(r"(invoice|gst|double|charged twice|refund|emi|coupon|deducted|billing)")

CLARIFY_QUESTION = (
    "Ask the customer one question before routing: is it (a) not working / a fault, (b) installation or demo, "
    "(c) delivery damaged, wrong or a return, (d) warranty or Shield, (e) a payment or invoice problem, "
    "(f) filters or spares, or (g) how to use it?"
)
NOISE_TOKENS = {"ordno", "regno", "order", "reg", "no", "please", "pls", "hi", "hello", "team", "sir",
                "namaste", "good", "morning", "thanks", "asap", "kindly", "very", "disappointed", "urgent",
                "for", "the", "of", "my", "with", "about", "regarding", "is", "and", "a", "to", "i"}
CONFIDENCE_FLOOR = 0.45  # below this the screen shows "check before routing"


def build_pipeline():
    words = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2)
    chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=3)
    return make_pipeline(make_union(words, chars), LogisticRegression(C=5, max_iter=3000))


def is_vague(text: str) -> bool:
    t = clean_text(text)
    return bool(VAGUE.search(t)) and not SPECIFIC.search(t)


def _word_reasons(pipe, x: str, team: str, k: int = 3):
    """Top word / phrase features pushing this record toward `team`."""
    union, clf = pipe.steps[0][1], pipe.steps[1][1]
    words = union.transformer_list[0][1]
    vec = words.transform([x])
    ci = list(clf.classes_).index(team)
    n_words = len(words.vocabulary_)
    coefs = clf.coef_[ci, :n_words]
    contrib = vec.multiply(coefs).toarray().ravel()
    names = words.get_feature_names_out()
    out = []
    for i in np.argsort(contrib)[::-1]:
        if contrib[i] <= 0 or len(out) >= k:
            break
        name = names[i]
        toks = name.split()
        if any(tok.startswith(("ch_", "pf_", "ws_")) or tok in NOISE_TOKENS for tok in toks):
            continue
        if any(name in prev or prev in name for prev in out):
            continue
        out.append(name)
    return out


def explain(pipe, rec: dict) -> dict:
    x = model_input(rec)
    probs = pipe.predict_proba([x])[0]
    classes = list(pipe.classes_)
    order = np.argsort(probs)[::-1]
    team = classes[order[0]]
    conf = float(probs[order[0]])
    text = clean_text(rec.get("request_text", ""))
    vague = is_vague(rec.get("request_text", ""))

    reasons = []
    phrases = _word_reasons(pipe, x, team)
    if phrases:
        reasons.append("Key words in the message: " + ", ".join(f'"{p}"' for p in phrases) + ".")
    if PAID.search(text) and team != "Billing" and not BILLING_PROBLEM.search(text):
        reasons.append("Customer mentions paying, but the problem is not the payment itself, so not Billing "
                       "(policy §3).")
    if team == "Billing":
        reasons.append("The problem is the payment itself (invoice, GST, charge, refund, EMI).")
    if vague:
        reasons.append("Message does not say what is wrong. Requests like this have historically ended up "
                       "in any of the seven teams, so this team is a best guess only.")
    elif conf < CONFIDENCE_FLOOR:
        reasons.append("Low confidence: two teams are close. A quick check by the agent is advised.")

    needs_check = vague or conf < CONFIDENCE_FLOOR
    return {
        "team": team,
        "confidence": round(conf, 3),
        "action": "clarify_first" if vague else ("check" if needs_check else "auto_route"),
        "reasons": reasons,
        "suggested_question": CLARIFY_QUESTION if vague else None,
        "alternatives": [
            {"team": classes[i], "confidence": round(float(probs[i]), 3)} for i in order[1:3]
        ],
    }


assert len(TEAMS) == 7
