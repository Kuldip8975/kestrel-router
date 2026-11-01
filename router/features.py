"""Shared text cleaning and feature building for the Kestrel router."""
import re

RENAMES = {"Installations": "Installs & Demo", "Consumables": "Filters & Consumables"}
TEAMS = [
    "Repairs", "Installs & Demo", "Filters & Consumables", "Billing",
    "Returns & Replacement", "Warranty Claims", "Product Advice",
]

# Legacy Zoho export double-encoded some characters (e.g. "Ã¢â‚¬Â¦" for "…", "Ã©" for "é").
_MOJIBAKE = [("Ã¢â‚¬Â¦", " "), ("â€¦", " "), ("Ã©", "e"), ("Â", " "), ("Ã", " ")]
# Order / registration numbers carry no routing signal; normalise them so they don't become features.
_ORDER = re.compile(r"\bKO\d+\b", re.I)
_REG = re.compile(r"\bSR\d+\b", re.I)


def clean_text(text: str) -> str:
    text = str(text or "")
    for bad, good in _MOJIBAKE:
        text = text.replace(bad, good)
    text = text.replace("é", "e")
    text = _ORDER.sub(" ordno ", text)
    text = _REG.sub(" regno ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def model_input(rec: dict) -> str:
    """Single string the model sees: cleaned text plus metadata tokens."""
    meta = " ".join([
        "ch_" + str(rec.get("channel", "")).lower(),
        "pf_" + str(rec.get("product_family", "")).lower().replace(" ", "_"),
        "ws_" + str(rec.get("warranty_status", "")).lower(),
    ])
    return clean_text(rec.get("request_text", "")) + " || " + meta
