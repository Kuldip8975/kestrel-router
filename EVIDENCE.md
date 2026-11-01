# Evidence: does it work, and how often doesn't it?

All numbers come from `python train.py`. Raw outputs are in `evidence/`.

## What "right" means

A routing decision is **right** when it names the team that actually closed the request (`final_team` in the resolution log, with renamed teams merged). That is the outcome Kestrel pays for, and the brief scores against "outcomes you do not have". The bot's label (`team_label`) is *not* used as truth, because it is a prediction too, and often a wrong one.

**Metric: accuracy** (share routed to the right team first time). Every misroute costs about the same (around Rs 700), so accuracy maps straight to rupees. Macro-F1 is reported too, so that small teams are not hidden: 0.843.

## How it was tested

**Rolling monthly back-test, no peeking at the future.** For each of the last six months (Jan–Jun 2026; 4,303 requests), the model was trained only on the months before it and tested on that month. That is how it will actually be used: trained on the past, routing next month's requests. The test set (Jul–Sep 2026) follows straight on from the training data.

| | Bot today | Model trained on bot labels (what was asked) | **Our model (trained on resolved team)** |
|---|---|---|---|
| Matches the bot's label | 100% | **96.4%** | 78.7% |
| **Right team** | **77.1%** | **77.4%** | **84.6%** |
| Right team, worst / best month | 74.1% / 78.9% | | 82.6% / 87.0% |

The middle column is the trap in the brief. It passes the "90% match" bar easily and is no better than the bot.

## Where it is right, and where nobody can be

| Request type (share of traffic) | Bot | Our model |
|---|---|---|
| States the problem ("error E3", "GST invoice wrong", "installer did not come"), 84% | 86.7% | **96.0%** |
| Says nothing specific ("please call me about my purifier", "issue with my order"), 16% | 27.2% | 25.2% |

For the vague 16%, we tried channel, product, warranty status, time of day, day of week, "mentions payment" and "has an order number" in a separate model. It scored 16.7%, against 17.3% for always guessing the biggest team. **The data contains no signal for these.** They need a question, not a better model. The service flags them as `clarify_first` and proposes the question.

## Confidence is honest

On the Apr–Jun 2026 hold-out (2,135 requests):

| Model confidence | Share of requests | Right |
|---|---|---|
| over 90% | 77% | **97.6%** |
| 70–90% | 5% | 81% |
| 45–70% | 6% | 45% |
| under 45% | 12% | 23% |

Requests marked `auto_route` (83% of traffic) were right **95.9%** of the time.

## Policy §3 (Billing only when the payment is the problem)

Hold-out messages that mention paying (192):

| | Bot | Our model |
|---|---|---|
| Sent to Billing | 73% | 18% |
| Really Billing | 18% | 18% |
| Right team | 33% | **86%** |

## Per team (hold-out)

| Team | Requests | Precision | Recall (ours) | Recall (bot) |
|---|---|---|---|---|
| Repairs | 498 | 0.84 | 0.90 | 0.77 |
| Installs & Demo | 321 | 0.84 | 0.84 | 0.70 |
| Returns & Replacement | 326 | 0.85 | 0.83 | 0.73 |
| Product Advice | 269 | 0.85 | 0.80 | 0.77 |
| Warranty Claims | 259 | 0.82 | 0.83 | 0.73 |
| Billing | 255 | 0.89 | 0.86 | 0.86 |
| Filters & Consumables | 207 | 0.84 | 0.83 | 0.84 |

The full confusion matrix is in `evidence/holdout_confusion_rows_true_cols_pred.csv`.

## The kinds of case it gets wrong

Hold-out errors: 326 of 2,135 (15.3%). All of them are listed in `evidence/holdout_errors.csv` by request ID; `train.py` writes a copy with message text to the git-ignored `evidence/private/`. Example messages quoted here are paraphrased patterns that recur many times in the data.

1. **Vague requests (77% of errors).** Covered above.
2. **Two problems in one message (most of the rest).** For example, "missing parts in box, someone contact me" (closed by Repairs, not Returns), or "loud noise, extend warranty" (closed by Warranty Claims, not Repairs). The model picks the stronger-sounding problem; the agent picked the other one.
3. **History that looks inconsistent.** "Air fryer arrived damaged, need replacement" was closed by Filters & Consumables. No router should learn that. We left such cases in the training data, rather than hand-editing history to flatter the score.
4. **A real model miss:** "AMC filter kit… payment deducted but order not placed" went to Filters & Consumables, but the payment *is* the problem, so it is Billing. A policy rule could fix this; we left it out because there were too few cases to test it.

## Expected score on the hidden test set

**84.6% accuracy (likely range 82.5–87%).**

We took the back-test accuracy separately for clear (96.0%) and vague (25.2%) requests and re-weighted them to the test set's own mix, which is 83.8% clear on our flag. The range is the worst and best back-test month. The main risk is that the hidden outcomes are not the resolving team: if they were the bot's labels, this would score about 79%.

## Money (assumptions in `train.py`)

- Cost of one misroute = 1.44 transfers (the average over the bot's 2,471 historical misroutes) × Rs 305, + Rs 260 for the extra contact = **Rs 698**.
- Volume = 2,178 test requests over 3 months × 4 = about 8,700 a year.
- Misroute cost: bot Rs 13.95 lakh a year, ours Rs 9.38 lakh a year. Saving Rs 4.57 lakh, plus Rs 3.2 lakh licence = **Rs 7.77 lakh a year**. Run cost Rs 0.

## Data problems found and handled

- **Renamed teams** appear under both names; merged (policy §5).
- **Zoho text corruption** in 11% of legacy rows (`Ã¢â‚¬Â¦`, `urgÃ©nt`); cleaned.
- **Zoho resolution times in UTC** (policy §9): 1,140 requests show as resolved *before* they were created. After adding 5h30m there are 0, and median resolution time is 9.5h in both systems. Not used for routing; fixed for the workload figures.
- **Inconsistent transfer counts:** 126 misrouted requests show 0 transfers, and 349 correctly routed requests show 1 or more (bounced out and back). The costing uses actual transfer counts.
