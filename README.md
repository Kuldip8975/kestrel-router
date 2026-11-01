# Kestrel Home — service-request router

<img width="2560" height="1280" alt="kestrel-banner" src="https://github.com/user-attachments/assets/f60aec82-3d66-4b23-9097-52904eda7db8" />


## The problem, in plain words

Kestrel Home sells air fryers, purifiers, fans and other appliances. When a customer writes in ("my purifier shows error E3", "I paid for installation but nobody came"), the request has to reach the right one of seven teams: Repairs, Installs & Demo, Filters & Consumables, Billing, Returns & Replacement, Warranty Claims or Product Advice.

A vendor's routing bot did this job for **Rs 3.2 lakh a year**, and it got it wrong often.

**One customer's story.** Priya buys a ceiling fan and pays Rs 499 for installation. A week later nobody has come, so she writes on WhatsApp: *"Fan delivered but not installed yet, I paid by card."* The bot sees the word "paid" and sends her to **Billing**. Billing can't send an installer, so they transfer her to **Installs & Demo**. Priya gets a second call and waits longer, and Kestrel pays for the transfer (Rs 305) and the extra contact (Rs 260).

That happened on **about one request in four**. Across 18 months of history, the bot sent requests to the right team only **77%** of the time. Each mistake cost about **Rs 700**: roughly **Rs 14 lakh a year** in wasted transfers, on top of the licence.

Kestrel asked for a replacement that "matches the bot's labels at 90%". But copying a router that is wrong a quarter of the time would copy its mistakes too.

## What we built

A router that learned from **where each request was actually resolved**, not from the bot's guesses:

| | Old bot | This router |
|---|---|---|
| Requests sent to the right team first time | 77 in 100 | **85 in 100** |
| ...when the message says what is wrong (84% of requests) | 87 in 100 | **96 in 100** |
| "I paid..." messages routed correctly | 33 in 100 | **86 in 100** |
| Cost per year | Rs 3.2 lakh licence + about Rs 14 lakh in misroutes | **Rs 0** to run + about Rs 9.4 lakh in misroutes |
| **Saving** | | **about Rs 7.8 lakh a year** |

With the new router, Priya's message goes straight to **Installs & Demo**, with the reason shown: *"Customer mentions paying, but the problem is not the payment itself, so not Billing."*

About 16% of messages say nothing useful, for example *"please call me about my purifier"*. No system can route those from the text. The router doesn't guess; it tells the agent to **ask the customer one question first** and suggests the question.

## In one line

Routes a new service request to one of Kestrel's seven teams, says how sure it is, explains why in plain words, and flags the requests that should get one clarifying question instead of a guess.

- Back-tested at **84.6% correct** against where requests were actually resolved (old bot: **77.1%**), and **96% correct** on the 84% of requests that say what the problem is.
- **Rs 0 per request.** No API key, no paid service, no extra dependency beyond scikit-learn.
- Built to run as a service: optional API-key auth, rate limiting, a batch endpoint for the CRM, a decision log, live-accuracy monitoring from feedback, drift alerts, versioned models, a release gate on retraining, and an automated test suite.

## Run it (clean machine, ~2 minutes)

Needs Python 3.10+.

```bash
git clone <this repo> && cd <repo>
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

Open http://localhost:8000. Click an example button or paste a message.

The trained model is committed (`models/router.joblib` + `models/model_card.json`), so the service starts without the data pack.

Run the tests (about 1 second):

```bash
python -m unittest discover -s tests -v
```

## API

All endpoints except `/` and `/health` need the header `X-API-Key: <key>` **when** `KESTREL_API_KEY` is set. With it unset (the default, for local demo), no key is needed.

### `POST /route`: route one request

```bash
curl -s localhost:8000/route -H "Content-Type: application/json" -d '{
  "request_id": "SR510822",
  "request_text": "machine delivered but not installed yet paid via card",
  "channel": "whatsapp", "product_family": "Ceiling Fan", "warranty_status": "in_warranty"
}'
```

```json
{
  "request_id": "SR510822",
  "team": "Installs & Demo",
  "confidence": 0.985,
  "action": "auto_route",
  "reasons": [
    "Key words in the message: \"installed yet\", \"delivered but\", \"but not\".",
    "Customer mentions paying, but the problem is not the payment itself, so not Billing (policy §3)."
  ],
  "suggested_question": null,
  "alternatives": [{"team": "Returns & Replacement", "confidence": 0.008}, ...],
  "model_version": "20261031-171839"
}
```

`action` is one of:
- `auto_route` — send it (83% of traffic, about 96% right).
- `check` — two teams are close; an agent should glance at it (rare).
- `clarify_first` — the message doesn't say what is wrong. Ask the `suggested_question`. `team` is a best guess only.

Only `request_text` is required. If `request_id` is missing, one is generated and returned.

### `POST /route/batch`: up to 500 requests in one call

```json
{"requests": [{"request_id": "SR1", "request_text": "..."}, {"request_id": "SR2", "request_text": "..."}]}
```

Returns `{"routed": n, "failed": n, "results": [...]}`. One bad record does not fail the whole batch.

### `POST /feedback`: tell the router where a request was really resolved

```json
{"request_id": "SR510822", "final_team": "Installs & Demo", "bot_team": "Billing", "transfers": 1}
```

The CRM should call this when a request closes. `bot_team` is optional; send it during the shadow trial to compare against the old bot. Old team names (Installations, Consumables) are accepted.

### `GET /metrics`

Decision volume, action mix, team volume, latency (p50/p95), **live accuracy** (decisions joined with feedback, overall and for `auto_route`), **model vs bot on the same requests**, the back-test numbers for comparison, and **alerts**:
- vague requests above 25% of traffic (history: about 16%);
- live accuracy below 80% once 200 or more requests have feedback;
- model trained on a different scikit-learn version than the one running.

### `GET /health` (no auth)

`{"ok": true, "model_version": "...", "auth_required": false, "error": null, "warning": null}`. Returns 503 if no model is loaded.

### `POST /admin/reload`

Loads a newly trained model without restarting the service.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` / `HOST` | `8000` / `0.0.0.0` | Where to listen |
| `KESTREL_API_KEY` | unset | Turns on API-key auth. The screen then asks for the key |
| `KESTREL_RATE_LIMIT` | `120` | Requests per minute per client IP; `0` turns it off |
| `KESTREL_LOG_DIR` | `./logs` | Decision and feedback logs (JSON Lines) |
| `KESTREL_LOG_TEXT` | `0` | `1` also stores the customer message in the decision log. Off by default for privacy |

Limits: request body up to 512 KB, message up to 4,000 characters, batch up to 500.

## Operating it (runbook)

**Deploy.** Run `python server.py` behind the company's reverse proxy (TLS ends there), with `KESTREL_API_KEY` set. A `Dockerfile` is included; it was written but **not built or tested** in our environment.

**Shadow trial (first two weeks).** The CRM calls `/route` for every new request but keeps using the bot's queue. When a request closes, it calls `/feedback` with `final_team` and `bot_team`. Check `/metrics → live_accuracy.model_accuracy_same_requests` against `bot_accuracy_same_requests`. Switch over when the model is clearly ahead on at least 1,000 requests.

**Monthly retrain.**
1. Export the latest closed requests from the CRM in the same columns as the data pack into `./data/`.
2. Run `python train.py`. It re-runs the time-ordered back-test, writes `evidence/`, and **only replaces the live model if the new back-test accuracy is within 1 point of the current one**. Otherwise it saves the new model to `models/candidate/` and exits without touching production. Use `--force` only after a human has reviewed why.
3. Run `python -m unittest discover -s tests`.
4. Call `POST /admin/reload` (or restart the service). `/health` shows the new `model_version`.

**Roll back.** Every model has a `model_card.json`. Keep the previous `models/` folder (or git tag), copy it back, and call `/admin/reload`.

**When an alert fires.** A rise in vague requests usually means a new channel or a new message template: look at recent `clarify_first` decisions. Falling live accuracy means the world has changed (new product, new team): retrain on a fresh export.

## Retrain and regenerate the submission files

With the data pack (`train.csv`, `test_unlabelled.csv`, `resolution_log.csv`, `teams.csv`, `sample_submission.csv`) in `./data/`:

```bash
python train.py              # ~1 min: back-test, evidence/, model + card, predictions.csv
python analysis_workload.py  # team workload for headcount planning -> evidence/workload_by_team.csv
```

## What's in the repo

| Path | What it is |
|---|---|
| `predictions.csv` | Team for each of the 2,178 test requests |
| `MEMO.md` | One-page memo to Ritu (non-technical) |
| `EVIDENCE.md` | How we know it works, and how often it doesn't |
| `FORM_ANSWERS.md` | Draft answers for the submission form |
| `RECORDING_SCRIPT.md` | Script for the 3-minute recording |
| `server.py`, `static/index.html` | The service and its screen |
| `router/` | Text cleaning, model, explanations |
| `train.py` | Training, back-test, rupee maths, release gate, predictions |
| `models/` | Live model and its model card |
| `tests/` | End-to-end tests of every endpoint |
| `analysis_workload.py` | Workload per team, with the Zoho UTC timestamp fix |
| `experiments/eval_laya.py` | Optional: compare against the open-source zero-shot model Laya |
| `evidence/` | Back-test by month, confusion matrix, per-team scores, hold-out errors (no customer text) |
| `Dockerfile` | Container image (untested) |

## Decisions we made (the brief said: decide, write it down, explain)

1. **We learned from where requests were resolved (`final_team`), not from the bot's label (`team_label`).** The bot's label is right only 77% of the time. A model that copies it reaches the requested "90% match" (we measured 96%) but is still wrong on 23% of requests. The brief scores us "against outcomes you do not have", which we read as the resolving team.
2. **Old team names are merged into the new ones** (Installations → Installs & Demo, Consumables → Filters & Consumables; policy §5 says responsibilities did not change). Predictions use the current names, because every test request is from after the rename.
3. **No language-model API in the product.** A local model is already at the ceiling the data allows on clear requests. An LLM would add a per-request bill Farhan explicitly asked us to avoid, and it cannot route "please call me" either; there is nothing in the text to route on.
4. **Raw customer data is not in this repo** (policy §10). `data/`, `logs/` and `evidence/private/` are git-ignored, and decision logs leave out message text by default. `predictions.csv` holds only request IDs and team names.
5. **Legacy Zoho text was cleaned** (garbled characters such as `Ã¢â‚¬Â¦`) and order/registration numbers masked before training.<img width="2560" height="1280" alt="kestrel-banner" src="https://github.com/user-attachments/assets/f04e1b60-3159-40b5-b69e-a9e2b4496497" />
