"""End-to-end tests for the router service. Standard library only.

    python -m unittest discover -s tests -v

Needs models/router.joblib (committed). Does not need the data pack.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = tempfile.mkdtemp(prefix="kestrel-test-logs-")
os.environ.update({"KESTREL_API_KEY": "test-key", "KESTREL_LOG_DIR": LOGS, "KESTREL_RATE_LIMIT": "0"})
sys.path.insert(0, ROOT)
import server  # noqa: E402

TEAMS = {"Repairs", "Installs & Demo", "Filters & Consumables", "Billing", "Returns & Replacement",
         "Warranty Claims", "Product Advice"}


def call(path, body=None, key="test-key", raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def setUpModule():
    global SRV, BASE
    SRV = server.make_server("127.0.0.1", 0)
    BASE = f"http://127.0.0.1:{SRV.server_address[1]}"
    threading.Thread(target=SRV.serve_forever, daemon=True).start()


def tearDownModule():
    SRV.shutdown()
    SRV.server_close()


class TestRouting(unittest.TestCase):
    def test_health_is_public_and_reports_version(self):
        code, body = call("/health", key=None)
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["auth_required"])
        self.assertNotEqual(body["model_version"], "unversioned")

    def test_screen_served(self):
        with urllib.request.urlopen(BASE + "/") as r:
            self.assertEqual(r.status, 200)
            self.assertIn(b"Where should this request go?", r.read())

    def test_auth_required(self):
        self.assertEqual(call("/route", {"request_text": "gst invoice wrong"}, key=None)[0], 401)
        self.assertEqual(call("/route", {"request_text": "gst invoice wrong"}, key="wrong")[0], 401)
        self.assertEqual(call("/metrics", key=None)[0], 401)

    def test_clear_cases_route_correctly(self):
        cases = {
            "gst invoice wrong name for induction cooktop": "Billing",
            "water purifier showing error code E3": "Repairs",
            "installer did not turn up for ceiling fan": "Installs & Demo",
            "air fryer arrived damaged, need replacement": "Returns & Replacement",
            "how to clean water purifier": "Product Advice",
            "claim status for purifier under warranty": "Warranty Claims",
            "need replacement filter candle for purifier": "Filters & Consumables",
        }
        for text, team in cases.items():
            code, body = call("/route", {"request_text": text, "request_id": "T1"})
            self.assertEqual(code, 200, text)
            self.assertEqual(body["team"], team, text)
            self.assertEqual(body["action"], "auto_route", text)
            self.assertTrue(body["reasons"], text)

    def test_policy3_paid_but_not_billing(self):
        code, body = call("/route", {"request_text": "machine delivered but not installed yet paid via card"})
        self.assertEqual(body["team"], "Installs & Demo")
        self.assertTrue(any("§3" in r for r in body["reasons"]))

    def test_vague_request_asks_first(self):
        code, body = call("/route", {"request_text": "please call back regarding my purifier"})
        self.assertEqual(code, 200)
        self.assertEqual(body["action"], "clarify_first")
        self.assertTrue(body["suggested_question"])
        self.assertIn(body["team"], TEAMS)

    def test_bad_input_is_polite(self):
        self.assertEqual(call("/route", {})[0], 400)
        self.assertEqual(call("/route", raw=b"not json")[0], 400)
        self.assertEqual(call("/route", [1, 2])[0], 400)
        self.assertEqual(call("/route", {"request_text": "x" * 5000})[0], 400)
        code, body = call("/route", {"request_text": "fan making noise", "channel": "fax"})
        self.assertEqual(code, 200)
        self.assertIn("warnings", body)
        self.assertEqual(call("/nope", {})[0], 404)

    def test_batch(self):
        reqs = [{"request_id": f"B{i}", "request_text": "fan making loud noise"} for i in range(5)] + [{}]
        code, body = call("/route/batch", {"requests": reqs})
        self.assertEqual(code, 200)
        self.assertEqual(body["routed"], 5)
        self.assertEqual(body["failed"], 1)
        self.assertEqual(call("/route/batch", {"requests": [{}] * 501})[0], 400)

    def test_feedback_and_live_metrics(self):
        call("/route", {"request_id": "F1", "request_text": "gst invoice wrong name"})
        call("/route", {"request_id": "F2", "request_text": "water purifier showing error code E3"})
        self.assertEqual(call("/feedback", {"request_id": "F1", "final_team": "Billing", "bot_team": "Billing"})[0], 200)
        self.assertEqual(call("/feedback", {"request_id": "F2", "final_team": "Repairs",
                                            "bot_team": "Consumables"})[0], 200)  # old team name accepted
        self.assertEqual(call("/feedback", {"request_id": "F3", "final_team": "Nobody"})[0], 400)
        code, m = call("/metrics")
        self.assertEqual(code, 200)
        self.assertGreaterEqual(m["live_accuracy"]["matched_to_decisions"], 2)
        self.assertIn("bot_accuracy_same_requests", m["live_accuracy"])
        self.assertIn("p95", m["latency_ms_since_start"])

    def test_privacy_no_text_in_logs_by_default(self):
        call("/route", {"request_id": "P1", "request_text": "secret customer words purifier error"})
        with open(os.path.join(LOGS, "decisions.jsonl")) as f:
            self.assertNotIn("secret customer words", f.read())

    def test_reload(self):
        code, body = call("/admin/reload", {})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
