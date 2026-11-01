"""Kestrel request router - production service.

Standard library HTTP server + the trained model. No paid services, no extra dependencies.

    python server.py                         -> http://localhost:8000

Endpoints (see README for request/response examples)
    GET  /                 agent screen
    GET  /health           liveness + model version (no auth)
    POST /route            one request -> team, confidence, action, reasons
    POST /route/batch      up to MAX_BATCH requests in one call (CRM integration)
    POST /feedback         report the team that actually resolved a request (+ optional bot team)
    GET  /metrics          volumes, action mix, latency, live accuracy vs feedback, drift alerts
    POST /admin/reload     load a newly trained model without restarting

Configuration (environment variables)
    PORT=8000  HOST=0.0.0.0
    KESTREL_API_KEY        if set, every endpoint except / and /health needs header  X-API-Key: <key>
    KESTREL_RATE_LIMIT     requests per minute per client IP (default 120; 0 = off)
    KESTREL_LOG_DIR        where decision and feedback logs go (default ./logs)
    KESTREL_LOG_TEXT=1     also store the customer message in the decision log (off by default: privacy)
"""
import hmac
import json
import os
import sys
import threading
import time
import traceback
import uuid
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")
API_KEY = os.environ.get("KESTREL_API_KEY", "")
RATE_LIMIT = int(os.environ.get("KESTREL_RATE_LIMIT", 120))
LOG_DIR = os.environ.get("KESTREL_LOG_DIR", os.path.join(HERE, "logs"))
LOG_TEXT = os.environ.get("KESTREL_LOG_TEXT", "0") == "1"
MODEL_PATH = os.path.join(HERE, "models", "router.joblib")
CARD_PATH = os.path.join(HERE, "models", "model_card.json")
PAGE = os.path.join(HERE, "static", "index.html")
MEDIA_DIR = os.path.join(HERE, "static", "media")
MEDIA_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".png": "image/png"}

MAX_BODY = 512 * 1024
MAX_TEXT = 4000
MAX_BATCH = 500
VALID = {
    "channel": {"ivr", "chat", "whatsapp", "email"},
    "warranty_status": {"in_warranty", "shield", "out_of_warranty"},
}
TEAM_ALIASES = {"Installations": "Installs & Demo", "Consumables": "Filters & Consumables"}
# Drift alerts: history says ~16% of requests are vague and ~77% get >90% confidence.
ALERT_VAGUE_SHARE = 0.25
ALERT_LIVE_ACCURACY = 0.80
ALERT_MIN_FEEDBACK = 200

STARTED = time.time()
_lock = threading.Lock()
_rate = defaultdict(deque)
_latency_ms = deque(maxlen=5000)
_counts = Counter()


# ---------------------------------------------------------------- model
class ModelHolder:
    def __init__(self):
        self.model = None
        self.card = {}
        self.error = None
        self.warning = None
        self.load()

    def load(self):
        try:
            import joblib
            import sklearn
            model = joblib.load(MODEL_PATH)
            card = {}
            if os.path.exists(CARD_PATH):
                with open(CARD_PATH) as f:
                    card = json.load(f)
            warning = None
            if card.get("sklearn_version") and card["sklearn_version"] != sklearn.__version__:
                warning = (f"Model trained with scikit-learn {card['sklearn_version']}, running "
                           f"{sklearn.__version__}. Retrain with `python train.py` to be safe.")
            self.model, self.card, self.error, self.warning = model, card, None, warning
            return True
        except Exception as exc:  # start anyway and explain, instead of crashing
            self.error = (f"Model not loaded ({exc.__class__.__name__}: {exc}). "
                          f"Run `python train.py` with the data pack in ./data/.")
            return False

    @property
    def version(self):
        return self.card.get("model_version", "unversioned")


HOLDER = ModelHolder()


# ---------------------------------------------------------------- logging
def _append(name, record):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with open(os.path.join(LOG_DIR, name), "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _read(name, limit=200_000):
    path = os.path.join(LOG_DIR, name)
    if not os.path.exists(path):
        return []
    with _lock, open(path, encoding="utf-8") as f:
        lines = deque(f, maxlen=limit)
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- core logic
def route_one(payload):
    """Returns (status, body). Never raises for bad input."""
    from router.model import explain

    if HOLDER.model is None:
        return 503, {"error": HOLDER.error}
    if not isinstance(payload, dict):
        return 400, {"error": "Each request must be a JSON object."}
    text = str(payload.get("request_text") or "").strip()
    if not text:
        return 400, {"error": "request_text is required (the customer's opening message or IVR transcript)."}
    if len(text) > MAX_TEXT:
        return 400, {"error": f"request_text is longer than {MAX_TEXT} characters."}
    warnings = []
    rec = dict(payload)
    for field, allowed in VALID.items():
        val = rec.get(field)
        if val and str(val).lower() not in allowed:
            warnings.append(f"Unknown {field} '{val}'; ignored, routed on the message text.")
            rec[field] = ""
    t0 = time.perf_counter()
    out = explain(HOLDER.model, rec)
    ms = round((time.perf_counter() - t0) * 1000, 2)
    request_id = str(payload.get("request_id") or f"auto-{uuid.uuid4().hex[:12]}")
    out = {"request_id": request_id, **out, "model_version": HOLDER.version}
    if warnings:
        out["warnings"] = warnings
    log = {"ts": _now(), "request_id": request_id, "team": out["team"], "confidence": out["confidence"],
           "action": out["action"], "model_version": HOLDER.version, "latency_ms": ms,
           "channel": rec.get("channel"), "product_family": rec.get("product_family")}
    if LOG_TEXT:
        log["request_text"] = text
    _append("decisions.jsonl", log)
    with _lock:
        _latency_ms.append(ms)
        _counts["routed"] += 1
        _counts["action:" + out["action"]] += 1
    return 200, out


def route_batch(payload):
    reqs = payload.get("requests") if isinstance(payload, dict) else None
    if not isinstance(reqs, list) or not reqs:
        return 400, {"error": 'Send {"requests": [ {...}, {...} ]}.'}
    if len(reqs) > MAX_BATCH:
        return 400, {"error": f"At most {MAX_BATCH} requests per batch; got {len(reqs)}."}
    if HOLDER.model is None:
        return 503, {"error": HOLDER.error}
    results = []
    for i, r in enumerate(reqs):
        code, body = route_one(r)
        results.append(body if code == 200 else {"index": i, "request_id": (r or {}).get("request_id")
                                                 if isinstance(r, dict) else None, **body})
    ok = sum(1 for r in results if "error" not in r)
    return 200, {"routed": ok, "failed": len(results) - ok, "results": results}


def feedback(payload):
    from router.features import TEAMS

    if not isinstance(payload, dict) or not payload.get("request_id"):
        return 400, {"error": "request_id is required."}
    final = TEAM_ALIASES.get(payload.get("final_team"), payload.get("final_team"))
    if final not in TEAMS:
        return 400, {"error": f"final_team must be one of: {', '.join(TEAMS)}."}
    rec = {"ts": _now(), "request_id": str(payload["request_id"]), "final_team": final}
    bot = TEAM_ALIASES.get(payload.get("bot_team"), payload.get("bot_team"))
    if bot:
        if bot not in TEAMS:
            return 400, {"error": f"bot_team must be one of: {', '.join(TEAMS)}."}
        rec["bot_team"] = bot
    if payload.get("transfers") is not None:
        rec["transfers"] = int(payload["transfers"])
    _append("feedback.jsonl", rec)
    return 200, {"ok": True}


def metrics():
    decisions = _read("decisions.jsonl")
    fb = {f["request_id"]: f for f in _read("feedback.jsonl")}  # latest feedback wins
    n = len(decisions)
    actions = Counter(d["action"] for d in decisions)
    teams = Counter(d["team"] for d in decisions)
    latest = {d["request_id"]: d for d in decisions}
    joined = [(latest[r], f) for r, f in fb.items() if r in latest]
    live = {"feedback_received": len(fb), "matched_to_decisions": len(joined)}
    if joined:
        live["model_accuracy"] = round(sum(d["team"] == f["final_team"] for d, f in joined) / len(joined), 4)
        auto = [(d, f) for d, f in joined if d["action"] == "auto_route"]
        if auto:
            live["model_accuracy_auto_route"] = round(sum(d["team"] == f["final_team"] for d, f in auto) / len(auto), 4)
        with_bot = [(d, f) for d, f in joined if f.get("bot_team")]
        if with_bot:
            live["bot_accuracy_same_requests"] = round(
                sum(f["bot_team"] == f["final_team"] for _, f in with_bot) / len(with_bot), 4)
            live["model_accuracy_same_requests"] = round(
                sum(d["team"] == f["final_team"] for d, f in with_bot) / len(with_bot), 4)
    lat = sorted(_latency_ms)
    alerts = []
    vague_share = actions["clarify_first"] / n if n else 0
    if n >= 200 and vague_share > ALERT_VAGUE_SHARE:
        alerts.append(f"Vague requests are {vague_share:.0%} of traffic (history: ~16%). Check for a new kind of "
                      f"request or a change in how messages arrive.")
    if len(joined) >= ALERT_MIN_FEEDBACK and live.get("model_accuracy", 1) < ALERT_LIVE_ACCURACY:
        alerts.append(f"Live accuracy {live['model_accuracy']:.1%} is below {ALERT_LIVE_ACCURACY:.0%} "
                      f"(back-test: {HOLDER.card.get('backtest_accuracy', 'n/a')}). Retrain on a fresh export.")
    if HOLDER.warning:
        alerts.append(HOLDER.warning)
    return 200, {
        "model_version": HOLDER.version,
        "uptime_seconds": round(time.time() - STARTED),
        "decisions_logged": n,
        "action_share": {k: round(v / n, 4) for k, v in actions.items()} if n else {},
        "team_volume": dict(teams.most_common()),
        "latency_ms_since_start": ({"p50": lat[len(lat) // 2], "p95": lat[int(len(lat) * 0.95) - 1] if len(lat) > 1 else lat[0]}
                                   if lat else {}),
        "live_accuracy": live,
        "backtest": {k: HOLDER.card.get(k) for k in ["backtest_accuracy", "backtest_accuracy_clear",
                                                      "backtest_accuracy_vague", "bot_accuracy_same_period"]},
        "alerts": alerts,
    }


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "KestrelRouter/1.0"
    sys_version = ""

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; media-src 'self'; img-src 'self'; script-src 'self' 'unsafe-inline'; "
                             "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                             "font-src https://fonts.gstatic.com; connect-src 'self'")
            self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def _send_media(self, name):
        """Serve a file from static/media with byte-range support, so the video can be seeked."""
        ctype = MEDIA_TYPES.get(os.path.splitext(name)[1].lower())
        path = os.path.join(MEDIA_DIR, os.path.basename(name))
        if not ctype or name != os.path.basename(name) or not os.path.isfile(path):
            return self._send(404, {"error": "Not found."})
        size = os.path.getsize(path)
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            try:
                a, b = rng[6:].split(",")[0].split("-")
                if a:
                    start, end = int(a), int(b) if b else size - 1
                else:
                    start, end = max(0, size - int(b)), size - 1
                end = min(end, size - 1)
                if start > end:
                    raise ValueError
                code = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "public, max-age=86400")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(256 * 1024, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # viewer skipped ahead or closed the page

    def _client(self):
        return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()

    def _authorised(self):
        if not API_KEY:
            return True
        given = self.headers.get("X-API-Key", "")
        return hmac.compare_digest(given.encode(), API_KEY.encode())

    def _rate_ok(self):
        if RATE_LIMIT <= 0:
            return True
        now, q = time.time(), None
        with _lock:
            q = _rate[self._client()]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= RATE_LIMIT:
                return False
            q.append(now)
        return True

    def _guard(self):
        """Auth + rate limit for API endpoints. Returns True if the request may proceed."""
        if not self._authorised():
            self._send(401, {"error": "Missing or wrong X-API-Key header."})
            return False
        if not self._rate_ok():
            self._send(429, {"error": f"Too many requests: limit is {RATE_LIMIT} per minute."})
            return False
        return True

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError(f"Body larger than {MAX_BODY // 1024} KB.")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self):
        try:
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                with open(PAGE, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path.startswith("/media/"):
                return self._send_media(path[len("/media/"):])
            if path == "/health":
                return self._send(200 if HOLDER.model else 503, {
                    "ok": HOLDER.model is not None, "model_version": HOLDER.version,
                    "auth_required": bool(API_KEY), "error": HOLDER.error, "warning": HOLDER.warning})
            if path == "/metrics":
                if self._guard():
                    self._send(*metrics())
                return
            self._send(404, {"error": "Not found. See README for the endpoints."})
        except Exception:
            traceback.print_exc()
            self._send(500, {"error": "Internal error; details are in the server log."})

    def do_POST(self):
        try:
            path = self.path.split("?")[0]
            handlers = {"/route": route_one, "/route/batch": route_batch, "/feedback": feedback}
            if path not in handlers and path != "/admin/reload":
                return self._send(404, {"error": "Not found. See README for the endpoints."})
            if not self._guard():
                return
            if path == "/admin/reload":
                ok = HOLDER.load()
                return self._send(200 if ok else 500, {"ok": ok, "model_version": HOLDER.version,
                                                       "error": HOLDER.error, "warning": HOLDER.warning})
            try:
                payload = self._body()
            except (ValueError, UnicodeDecodeError) as exc:
                msg = str(exc) if "larger" in str(exc) else "Body must be valid UTF-8 JSON."
                return self._send(400 if "larger" not in msg else 413, {"error": msg})
            self._send(*handlers[path](payload))
        except Exception:
            traceback.print_exc()
            self._send(500, {"error": "Internal error; details are in the server log."})

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{_now()} {self._client()} {fmt % args}\n")


def make_server(host=HOST, port=PORT):
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    srv = make_server()
    status = f"model {HOLDER.version}" if HOLDER.model else f"[WARNING] {HOLDER.error}"
    print(f"Kestrel router on http://localhost:{PORT}  ({status}; auth {'on' if API_KEY else 'off'}; "
          f"logs in {LOG_DIR})")
    if HOLDER.warning:
        print(f"[WARNING] {HOLDER.warning}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
        srv.server_close()